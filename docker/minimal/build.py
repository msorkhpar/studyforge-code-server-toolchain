"""Build the runner image for a DECLARED SET of runtimes, from pins.json.

**What it does.** Reads `pins.json`, refuses a set it does not pin (naming what
is pinned), computes the image tag from the build's inputs, and runs
`docker build` with every ARG the Dockerfile needs. No ARG has a default, so
this script is the only way the Dockerfile builds.

**How you use it.** From the component root:

    python3 docker/minimal/build.py --runtimes java,maven
    python3 docker/minimal/build.py --runtimes java,maven --print-tag
    python3 docker/minimal/build.py --runtimes java,maven --prime path/to/prime
    python3 docker/minimal/build.py --record-maven     # re-derive the Maven warm pins

`--prime DIR` warms a corpus's declared practice dependencies into the image
from that corpus's own build files, so a graded run resolves them with no
network. The contract is `prime/prime.py`'s — shared with the
editor — and the directory is mounted read-only as the named context
`consumer-prime`; its digest moves the tag. Without it the context is an empty
directory and nothing is warmed.
`--root DIR` builds a different copy of the component (the tests use it to
plant a bad pin in a temporary copy); `--platform` defaults to this machine's.

**Depends on.** The standard library, `plan.py` beside it, `prime/prime.py`
for the prime contract, and a Docker CLI with BuildKit. ⛔ It never mounts a
socket and never runs a container.
"""

from __future__ import annotations

import argparse
import platform as host
import subprocess
import sys
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(COMPONENT / "prime"))
import plan as planning  # noqa: E402
import prime as prime_contract  # noqa: E402

_MACHINES = {"x86_64": "linux/amd64", "amd64": "linux/amd64", "aarch64": "linux/arm64", "arm64": "linux/arm64"}
#: The warmers' directory, relative to the component: a build input when, and
#: only when, a prime is given.
WARMERS = "prime"
#: What a PRIMED build's digest is taken over: the runner's own inputs, plus
#: the warmers, which run in such a build and in no other. ⛔ Declared once,
#: here, and never listed again — `tests/build_inputs.py` copies a planted
#: context by READING this, so a new input is one edit.
PRIMED_INPUT_ROOTS = planning.INPUT_ROOTS + (WARMERS,)


def host_platform() -> str:
    machine = host.machine().lower()
    return _MACHINES.get(machine, f"linux/{machine}")


def planned(root: Path, platform: str, names, prime: Path | None = None) -> planning.Plan:
    """The build for the declared set, or `Refused` before Docker is touched.

    ⭐ A prime is READ for its shape and GUARDED against `pins.json` here, so a
    prime the declared set cannot build, or one naming another version, is
    refused before `docker build` starts — as it is for the editor.
    """
    pins = planning.load(root)
    read = prime_contract.read(prime) if prime is not None else None
    # ⭐ The warmers RUN in a primed build, so they are an input to THAT image
    # and to no other one: taking the digest over `PRIMED_INPUT_ROOTS` only
    # when a prime is given leaves every unprimed tag exactly where it was,
    # which the rule "an editor-only change moves no runner tag" requires (`prime/` is an input of the
    # editor's image too).
    roots = planning.INPUT_ROOTS if read is None else PRIMED_INPUT_ROOTS
    built = planning.plan(pins, names, platform, planning.inputs_digest(root, roots), read)
    if read is not None:
        prime_contract.guard(read, pins, built.names)
    return built


def empty_context(root: Path) -> Path:
    """An empty directory standing in for a consumer's prime.

    ⛔ The Dockerfile's warm step binds the named context `consumer-prime` in
    EVERY build, so the flag is never optional. With no prime it names this
    directory, both switches are `no`, and nothing reads it.
    """
    path = Path(root) / ".work" / "no-prime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def docker_command(root: Path, built: planning.Plan, target: str = "runner", output: str | None = None,
                   prime: Path | None = None) -> list[str]:
    command = ["docker", "build", "--progress=plain", "--platform", built.platform,
               "-f", str(root / planning.DOCKERFILE), "--target", target,
               "--build-context", f"consumer-prime={prime or empty_context(root)}"]
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
    parser.add_argument("--prime", default=None,
                        help="a corpus's prime directory to warm its practice dependencies from")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    names = [name for name in args.runtimes.split(",") if name]
    prime = Path(args.prime).resolve() if args.prime else None
    if args.record_maven:
        names, prime = ["java", "maven"], None
    try:
        built = planned(root, args.platform or host_platform(), names, prime)
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
        command = docker_command(root, built, prime=prime)
    completed = subprocess.run(command, stdin=subprocess.DEVNULL)
    if completed.returncode == 0:
        print(built.tag if not args.record_maven else "recorded: .work/record/maven-warm.json")
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
