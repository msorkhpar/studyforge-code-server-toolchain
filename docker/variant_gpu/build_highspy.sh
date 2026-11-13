# The highs-build stage's work (NO network): highspy from the pinned HiGHS source, with CUDA.
# Reads CUDA_REQUIREMENTS, HIGHS_BUILD_REQUIREMENTS, HIGHS_EDITS, CUDA_ARCHITECTURES, BUILD_JOBS, VENV.
# Writes one wheel to /out. The build venv, the CUDA toolkit and the compiler stay in this stage.
set -eu
# ⭐ Fixed paths, not mktemp: a path can end up in the binaries (the linker adds the CUDA library directory to
#    the RUNPATH), so the build venv sits where the image's cuOpt venv will, and the source in /build.
work=/build
mkdir -p "$work"
pyver="$(python3 -c 'import sys; print(f"python{sys.version_info[0]}.{sys.version_info[1]}")')"

# 1. A venv for this build only, at the cuOpt venv's own path: the build tools and the CUDA wheels, offline and
#    hashed. It sees the image's own numpy and packaging (system site packages), the versions the profile pins.
python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/python" -m pip install --no-index --no-cache-dir --require-hashes --no-deps \
  --find-links /fetched/build -r "/files/${HIGHS_BUILD_REQUIREMENTS}"
"$VENV/bin/python" -m pip install --no-index --no-cache-dir --require-hashes --no-deps \
  --find-links /fetched/cuda -r "/files/${CUDA_REQUIREMENTS}"
cu="$VENV/lib/$pyver/site-packages/nvidia/cu13"
test -x "$cu/bin/nvcc" || { echo "build: no nvcc at $cu/bin" >&2; exit 1; }
# The wheels ship versioned libraries only; the linker and FindCUDAToolkit look for the unversioned name.
for lib in cudart cublas cublasLt cusparse; do
  found="$(ls "$cu/lib/lib$lib.so."* | head -n 1)"
  ln -sf "$(basename "$found")" "$cu/lib/lib$lib.so"
done
"$cu/bin/nvcc" --version | tail -n 2

# 2. The source, by its pinned digest (ADD --checksum), edited and checked file by file.
tar xzf /src/highs.tar.gz -C "$work"
python3 /recipe/edit_source.py "/files/${HIGHS_EDITS}" "$work/HiGHS"

# 3. The wheel. ⭐ The RUNPATH names $ORIGIN (cudalin beside _core) and the cuOpt venv's CUDA libraries,
#    the one copy of them in the image. ⛔ BUILD_JOBS bounds the compile: a CUDA build is heavy.
export PATH="$cu/bin:$PATH" CUDACXX="$cu/bin/nvcc" CMAKE_BUILD_PARALLEL_LEVEL="${BUILD_JOBS}"
mkdir -p /out
"$VENV/bin/python" -m pip wheel --no-index --no-build-isolation --no-deps --no-cache-dir -w /out \
  -C cmake.define.CUPDLP_GPU=ON \
  -C "cmake.define.CUDAToolkit_ROOT=$cu" \
  -C "cmake.define.CMAKE_CUDA_COMPILER=$cu/bin/nvcc" \
  -C "cmake.define.CMAKE_CUDA_ARCHITECTURES=${CUDA_ARCHITECTURES}" \
  -C cmake.define.CMAKE_CUDA_RUNTIME_LIBRARY=Shared \
  -C "cmake.define.CMAKE_INSTALL_RPATH=\$ORIGIN;${VENV}/lib/$pyver/site-packages/nvidia/cu13/lib" \
  -C build.verbose=true \
  -C build-dir=/build/cmake \
  "$work/HiGHS"

# 4. What the wheel holds: the module, the CUDA library beside it, and a RUNPATH that names both places.
wheel="$(ls /out/highspy-*.whl)"
python3 -I -m zipfile -l "$wheel" | grep -E '_core|libcudalin' \
  || { echo "build: the wheel holds no _core or libcudalin" >&2; exit 1; }
check="$(mktemp -d)"
python3 -I -m zipfile -e "$wheel" "$check"
for so in "$check"/highspy/_core*.so "$check"/highspy/libcudalin.so; do
  readelf -d "$so" | grep -E 'RUNPATH|RPATH|NEEDED'
done
readelf -d "$check"/highspy/_core*.so | grep -q 'libcudalin.so' \
  || { echo "build: _core does not link libcudalin; the GPU PDLP is not in the module" >&2; exit 1; }
if readelf -d "$check"/highspy/*.so | grep -E 'RUNPATH|RPATH' | grep -q -E '/tmp|/build'; then
  echo "build: a RUNPATH names a build directory" >&2; exit 1
fi
sha256sum "$wheel"
rm -rf "$work" "$check" "$VENV" /root/.cache
