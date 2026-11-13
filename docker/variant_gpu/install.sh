# The variant's install (NO network). `install.sh full` builds the variant; `install.sh highs-check`
# builds and proves the HiGHS half alone: the CUDA libraries in the venv, no cuOpt.
# Reads CUDA_REQUIREMENTS, VENV_REQUIREMENTS, VENV_IMPORTS, HIGHS_REPLACES, VENV.
set -eu
mode="$1"
offline="PIP_INDEX_URL=https://index.invalid/simple PIP_RETRIES=0 PIP_TIMEOUT=2"

# 1. cuOpt's venv, apart from the image's python3: its closure pins pandas and numpy the profile cannot.
#    The CUDA wheels are installed here once; highspy finds them by its RUNPATH.
python3 -m venv "$VENV"
if [ "$mode" = full ]; then
  set --
  for req in ${VENV_REQUIREMENTS}; do set -- "$@" -r "/files/$req"; done
  env $offline "$VENV/bin/python" -m pip install --no-index --no-cache-dir --require-hashes \
    --find-links /fetched/cuda --find-links /fetched/cuopt "$@"
  "$VENV/bin/python" -m pip check
  IFS=','
  for mod in ${VENV_IMPORTS}; do
    "$VENV/bin/python" -c "import $mod" || { echo "install: venv: import $mod failed" >&2; exit 1; }
    echo "proof: $VENV/bin/python imports $mod"
  done
  unset IFS
else
  env $offline "$VENV/bin/python" -m pip install --no-index --no-cache-dir --require-hashes --no-deps \
    --find-links /fetched/cuda -r "/files/${CUDA_REQUIREMENTS}"
fi

# 2. highspy: the profile's wheel out, the CUDA build of the same release in.
installed="$(python3 -m pip show highspy | sed -n 's/^Version: //p')"
[ "highspy==$installed" = "${HIGHS_REPLACES}" ] \
  || { echo "install: the profile holds highspy $installed, and this variant replaces ${HIGHS_REPLACES}" >&2; exit 1; }
python3 -m pip uninstall -y highspy
env $offline python3 -m pip install --no-index --no-deps --no-cache-dir /out/highspy-*.whl
# The same version string as the wheel it replaces: a pin check reads the same answer on both images.
[ "$(python3 -m pip show highspy | sed -n 's/^Version: //p')" = "$installed" ] \
  || { echo "install: the CUDA build does not report highspy $installed" >&2; exit 1; }
python3 -m pip check
python3 /recipe/proof.py "$VENV"

# 3. What the variant holds, for a program to read (gpu_info) and a reader to see.
python3 - "$VENV" "$mode" <<'EOF'
import hashlib, json, pathlib, subprocess, sys
venv, mode = sys.argv[1], sys.argv[2]
wheel = next(pathlib.Path("/out").glob("highspy-*.whl"))
def version(python, dist):
    out = subprocess.run([python, "-m", "pip", "show", dist], capture_output=True, text=True).stdout
    return next((l.split(": ", 1)[1] for l in out.splitlines() if l.startswith("Version: ")), None)
record = {
    "variant": "optimization-gpu",
    "build": mode,
    "device": "gpu",
    "highspy": version("python3", "highspy"),
    "highspy_wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
    "cuda_runtime": version(f"{venv}/bin/python", "nvidia-cuda-runtime"),
    "cuopt": version(f"{venv}/bin/python", "cuopt-cu13") if mode == "full" else None,
    "cuopt_python": f"{venv}/bin/python" if mode == "full" else None,
}
pathlib.Path("/opt/gpu").mkdir(parents=True, exist_ok=True)
pathlib.Path("/opt/gpu/variant.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps(record))
EOF

rm -rf /root/.cache
chmod -R a+rX /opt/gpu
