"""Build the editor image: the runner for the editor's set first, then code-server on it.

**What it does.** Reads `pins.json` and `editor-pins.json`, refuses (naming
what is missing) anything the editor needs that is not pinned, computes the
editor's tag, builds the runner for the editor's set with the runner's own
build command (`docker/minimal/build.py`), and then runs `docker build` on
`docker/editor/Dockerfile` with every ARG it needs. No ARG has a default, so
this script is the only way that Dockerfile builds.

**How you use it.** From the component root:

    python3 docker/editor/build.py
    python3 docker/editor/build.py --print-tag

`--root DIR` builds a different copy of the component (the tests plant a
defect in a temporary copy); `--platform` defaults to this machine's.

**Depends on.** The standard library, `editor_plan.py` beside it, the runner's
`build.py` and `plan.py`, and a Docker CLI with BuildKit. ⛔ It never mounts a
socket and never runs a container.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "minimal"))
import build as runner_build  # noqa: E402
import editor_plan  # noqa: E402

COMPONENT = Path(__file__).resolve().parents[2]


def planned(root: Path, platform: str) -> editor_plan.EditorPlan:
    """The editor's plan on `platform`, or `Refused` before Docker is touched."""
    runner = editor_plan.runner_plan
    pins = runner.load(root)
    runner_built = runner.plan(pins, list(editor_plan.EDITOR_SET), platform, runner.inputs_digest(root))
    return editor_plan.plan(pins, editor_plan.load(root), runner_built, editor_plan.inputs_digest(root))


def runner_command(root: Path, platform: str) -> list[str]:
    """The runner's own build for the editor's set, with its FINAL stage never served from cache.

    ⛔ Measured on BuildKit v0.31.1 (TC-01/13): after a `python`-only runner
    build, the full set's `COPY --from=java / /` on the same base was served from
    cache and left /opt EMPTY. The runner's own /opt check refused it, so no
    wrong image was tagged, but the build failed. Rebuilding only the final
    stage (the downloads stay cached) makes the editor's build deterministic.
    The runner's own `build.py` is unchanged: that defect is its owner's.
    """
    runner = editor_plan.runner_plan
    built = runner.plan(runner.load(root), list(editor_plan.EDITOR_SET), platform, runner.inputs_digest(root))
    command = runner_build.docker_command(root, built)
    return command[:2] + ["--no-cache-filter", "runner"] + command[2:]


def docker_command(root: Path, built: editor_plan.EditorPlan) -> list[str]:
    command = ["docker", "build", "--progress=plain", "--platform", built.platform,
               "-f", str(root / editor_plan.DOCKERFILE), "--target", "editor", "-t", built.tag]
    for key in sorted(built.build_args):
        command += ["--build-arg", f"{key}={built.build_args[key]}"]
    return command + [str(root)]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--platform", default=None)
    parser.add_argument("--root", default=str(COMPONENT))
    parser.add_argument("--print-tag", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    platform = args.platform or runner_build.host_platform()
    try:
        built = planned(root, platform)
    except editor_plan.Refused as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 2
    if args.print_tag:
        print(built.tag)
        return 0
    # A runner tag exists only once its own build checked /opt and every version,
    # and the tag digests its inputs — so an existing one is reused, which also
    # keeps the editor's layers cached across builds.
    present = subprocess.run(["docker", "image", "inspect", built.build_args["RUNNER_IMAGE"]],
                             stdin=subprocess.DEVNULL, capture_output=True)
    if present.returncode != 0:
        runner = subprocess.run(runner_command(root, platform), stdin=subprocess.DEVNULL)
        if runner.returncode != 0:
            return runner.returncode
    completed = subprocess.run(docker_command(root, built), stdin=subprocess.DEVNULL)
    if completed.returncode == 0:
        print(built.tag)
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
