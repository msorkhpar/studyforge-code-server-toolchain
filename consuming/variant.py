"""Which image of a profile to run: the profile's own (CPU) image, or its GPU variant when it can run.

**What it does.** A profile may have a GPU variant (`variants/<name>.json`, `layers_on_profile`). This
module picks one image for a consumer, the same way for every consumer, so none keeps its own rule:

* the GPU variant only when (a) its image is present locally, and (b) Docker reaches a GPU with it:
  `docker run --rm --gpus all --network none --entrypoint nvidia-smi <gpu image> -L` exits 0 and lists a GPU;
* otherwise the profile's own image, with no error: a missing image, a Docker with no GPU runtime, or a
  host with no GPU is a fallback, not a failure;
* the environment variable `TOOLCHAIN_VARIANT` forces either: `cpu` always takes the profile's image,
  `gpu` takes the variant and REFUSES (exit 2) when the image is absent or the probe fails, and `auto`
  (or unset) is the rule above.

**Which Docker engine.** A host may run more than one: a Docker context without GPU passthrough (which
may be the current context) and an engine whose `nvidia` runtime reaches the GPU. The variant is looked up
and probed on the GPU engine: `TOOLCHAIN_GPU_DOCKER_HOST` when it is set; otherwise the current context
when its `docker info` lists an `nvidia` runtime; otherwise the local socket `unix:///var/run/docker.sock`
when it exists and lists one. The CPU image always runs on the current context. `--choose` says which
engine in `docker_host` (null: the current context); a consumer sets `DOCKER_HOST` to it for that run.

**How you use it.** From the component root:

    python3 consuming/variant.py --profile optimization --image runner --runtimes python --choose
    python3 consuming/variant.py --profile optimization --image runner --runtimes python --list

`--choose` prints one JSON line: `{"variant": "gpu"|"cpu", "image": <repository:tag>, "docker_args": [...],
"docker_host": <a DOCKER_HOST value, or null for the current context>, "reason": ...}`. `docker_args` go before the image in `docker run` (`--gpus all` for the variant).
`--list` prints the images the profile has, CPU first, and starts no container.

**Depends on.** The variant and profile planners, read-only, and the `docker` CLI for `--choose`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docker" / "variant_gpu"))
import variant_plan  # noqa: E402

package_kinds = variant_plan.package_kinds
Refused = variant_plan.Refused

ENV = "TOOLCHAIN_VARIANT"
HOST_ENV = "TOOLCHAIN_GPU_DOCKER_HOST"
NATIVE = "unix:///var/run/docker.sock"
MODES = ("auto", "cpu", "gpu")
GPU_ARGS = ["--gpus", "all"]
PROBE_SECONDS = 60


def images(root: Path, profile: str, image: str, names, platform: str) -> list[dict]:
    """The profile's own image first, then each variant layered on it that is built for `image`."""
    found = [{"variant": "cpu", "name": profile, "image": package_kinds.plan(root, profile, image, names, platform).tag}]
    for name in variant_plan.known(root):
        variant = variant_plan.load(root, name)
        if variant.get("layers_on_profile") == profile and image in variant.get("images", []):
            built = variant_plan.plan(root, name, image, names, platform)
            found.append({"variant": variant["device"], "name": name, "image": built.tag})
    return found


def _env(host: str | None) -> dict:
    env = dict(os.environ)
    if host:
        env["DOCKER_HOST"] = host
    return env


def has_nvidia(host: str | None, run=subprocess.run) -> bool:
    """True when the engine at `host` (None: the current context) lists an `nvidia` runtime."""
    try:
        done = run(["docker", "info", "--format", "{{json .Runtimes}}"], capture_output=True, text=True,
                   stdin=subprocess.DEVNULL, env=_env(host), timeout=PROBE_SECONDS)
    except subprocess.TimeoutExpired:
        return False
    return done.returncode == 0 and '"nvidia"' in done.stdout


def gpu_host(run=subprocess.run, exists=os.path.exists) -> tuple[str | None, str]:
    """The engine the GPU variant runs on: (DOCKER_HOST value or None for the current context, or why there is none)."""
    if os.environ.get(HOST_ENV):
        return os.environ[HOST_ENV], f"{HOST_ENV}"
    if has_nvidia(None, run):
        return None, "the current context has the nvidia runtime"
    if exists(NATIVE.removeprefix("unix://")) and has_nvidia(NATIVE, run):
        return NATIVE, "the engine at the local socket has the nvidia runtime"
    return None, "no engine lists an nvidia runtime"


def present(tag: str, run=subprocess.run, host: str | None = None) -> bool:
    done = run(["docker", "image", "inspect", "--format", "{{.Id}}", tag], capture_output=True, text=True,
               stdin=subprocess.DEVNULL, env=_env(host))
    return done.returncode == 0


def probe(tag: str, run=subprocess.run, host: str | None = None) -> tuple[bool, str]:
    """True when Docker starts the image with a GPU and nvidia-smi lists one; the second value says why not."""
    command = ["docker", "run", "--rm", *GPU_ARGS, "--network", "none", "--entrypoint", "nvidia-smi", tag, "-L"]
    try:
        done = run(command, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=PROBE_SECONDS,
                   env=_env(host))
    except subprocess.TimeoutExpired:
        return False, f"the GPU probe did not finish in {PROBE_SECONDS} s"
    if done.returncode == 0 and "GPU" in done.stdout:
        # ⛔ The device's UUID identifies one machine's card; the reason is printed and logged, so it is cut.
        return True, re.sub(r"\s*\(UUID: [^)]*\)", "", done.stdout.strip().splitlines()[0])
    reason = (done.stderr or done.stdout).strip().splitlines()
    return False, f"the GPU probe failed: {reason[-1][:200] if reason else f'exit {done.returncode}'}"


def choose(root: Path, profile: str, image: str, names, platform: str, mode: str | None = None,
           run=subprocess.run, exists=os.path.exists) -> dict:
    mode = (mode or "auto").strip().lower()
    if mode not in MODES:
        raise Refused(f"{ENV}={mode!r}: it is one of {list(MODES)}")
    found = images(root, profile, image, names, platform)
    cpu, gpus = found[0], [f for f in found[1:] if f["variant"] == "gpu"]
    fallback = dict(cpu, docker_args=[], docker_host=None)
    if mode == "cpu":
        return dict(fallback, reason=f"{ENV}=cpu")
    if not gpus:
        if mode == "gpu":
            raise Refused(f"{ENV}=gpu, and profile {profile!r} has no GPU variant for {image}")
        return dict(fallback, reason="the profile has no GPU variant")
    gpu = gpus[0]
    host, where = gpu_host(run, exists)
    engine = host or "the current context"
    if not present(gpu["image"], run, host):
        if mode == "gpu":
            raise Refused(f"{ENV}=gpu, and the GPU image {gpu['image']} is not present on {engine} ({where})")
        return dict(fallback, reason=f"the GPU image {gpu['image']} is not present on {engine} ({where})")
    ok, why = probe(gpu["image"], run, host)
    if not ok:
        if mode == "gpu":
            raise Refused(f"{ENV}=gpu, and on {engine} {why}")
        return dict(fallback, reason=f"on {engine} {why}")
    return dict(gpu, docker_args=list(GPU_ARGS), docker_host=host, reason=f"{why}, on {engine}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", required=True)
    parser.add_argument("--image", choices=("runner", "editor"), required=True)
    parser.add_argument("--runtimes", default="")
    parser.add_argument("--platform", default="linux/amd64")
    parser.add_argument("--root", default=str(ROOT))
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--choose", action="store_true")
    what.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)
    names = [n for n in args.runtimes.split(",") if n]
    root = Path(args.root).resolve()
    try:
        if args.list:
            for one in images(root, args.profile, args.image, names, args.platform):
                print(json.dumps(one))
            return 0
        print(json.dumps(choose(root, args.profile, args.image, names, args.platform, os.environ.get(ENV))))
        return 0
    except Refused as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
