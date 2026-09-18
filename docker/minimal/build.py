"""Build the runner image for a DECLARED SET of runtimes, from pins.json.

**What it does.** Reads `pins.json`, refuses a set it does not pin (naming what
is pinned), computes the image tag from the build's inputs, and runs
`docker build` with every ARG the Dockerfile needs. No ARG has a default, so
this script is the only way the Dockerfile builds.

**How you use it.** From the component root:

    python3 docker/minimal/build.py --runtimes java,maven
    python3 docker/minimal/build.py --runtimes java,maven --print-tag
    python3 docker/minimal/build.py --record-maven     # re-derive the Maven warm pins

`--root DIR` builds a different copy of the component (the tests use it to
plant a bad pin in a temporary copy); `--platform` defaults to this machine's.

**Depends on.** The standard library, `plan.py` beside it, and a Docker CLI
with BuildKit. ⛔ It never mounts a socket and never runs a container.
"""

from __future__ import annotations

import argparse
import platform as host
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plan as planning  # noqa: E402

COMPONENT = Path(__file__).resolve().parents[2]
_MACHINES = {"x86_64": "linux/amd64", "amd64": "linux/amd64", "aarch64": "linux/arm64", "arm64": "linux/arm64"}


def host_platform() -> str:
    machine = host.machine().lower()
    return _MACHINES.get(machine, f"linux/{machine}")


def docker_command(root: Path, built: planning.Plan, target: str = "runner", output: str | None = None) -> list[str]:
    command = ["docker", "build", "--progress=plain", "--platform", built.platform,
               "-f", str(root / planning.DOCKERFILE), "--target", target]
    command += ["--output", output] if output else ["-t", built.tag]
    for key in sorted(built.build_args):
        command += ["--build-arg", f"{key}={built.build_args[key]}"]
    return command + [str(root)]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runtimes", default="", help="the declared set, comma-separated")
    parser.add_argument("--platform", default=None)
    parser.add_argument("--root", default=str(COMPONENT))
    parser.add_argument("--print-tag", action="store_true")
    parser.add_argument("--record-maven", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    names = [name for name in args.runtimes.split(",") if name]
    if args.record_maven:
        names = ["java", "maven"]
    try:
        pins = planning.load(root)
        built = planning.plan(pins, names, args.platform or host_platform(), planning.inputs_digest(root))
    except planning.Refused as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 2
    if args.print_tag:
        print(built.tag)
        return 0
    if args.record_maven:
        out = root / ".work" / "record"
        command = docker_command(root, built, target="maven-record-out", output=f"type=local,dest={out}")
    else:
        command = docker_command(root, built)
    completed = subprocess.run(command, stdin=subprocess.DEVNULL)
    if completed.returncode == 0:
        print(built.tag if not args.record_maven else "recorded: .work/record/maven-warm.json")
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
