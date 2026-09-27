"""Every image this component builds, printed as the `docker build` its own build runs.

**What it does.** Plans one of four builds from this checkout and prints it as
one JSON document: the unprimed `runner` and `editor` that every consumer of a
declared set shares, and the two COURSE LAYERS, `runner-prime` and
`editor-prime`, that warm one consumer's prime on top of them
(`docker/prime/Dockerfile`). The document names the Dockerfile, the target,
every ARG, the named contexts, the images each build starts FROM, which of
those this component builds itself, the tag and the input roots the build
context must carry.

**How you use it.** From the component root:

    python3 consuming/builds.py runner --runtimes java,maven
    python3 consuming/builds.py editor --runtimes java,maven
    python3 consuming/builds.py runner-prime --runtimes java,maven --prime DIR
    python3 consuming/builds.py editor-prime --runtimes java,maven --prime DIR

`described(root, image, names, platform, prime)` is the same answer as a dict.

**Depends on.** The standard library and the three plans the build scripts
read: `docker/minimal/plan.py`, `docker/editor/editor_plan.py` and
`prime/prime.py`. ⛔ It runs no Docker, reads no Dockerfile and prints no path
of this host: the context is this component's root, spelled `.`, and the prime
is the named context `consumer-prime`, which the consumer supplies itself.

## ⭐ Why the build is printed as data

⚠️ A consumer that builds with `docker compose build` writes `args`, `target`
and `additional_contexts` into its compose file. Copied from the Dockerfile,
they would be a fork that drifts in silence; read from here, they are the plans'
own values, so the image compose builds is the image `build.py` builds, and a
tag this prints is the tag `build.py --print-tag` prints.

## ⛔ What a build from this data does not do

The editor's two SESSION proofs, `activation.py` and `confinement.py`, run in
`docker/editor/build.py` between the build and the tag, with a browser. A
compose build cannot run them. ⭐ The document says so in `proved_by`, and the
consumer that publishes an editor built from this data runs both against the
built image before anybody pulls it: every check inside the Dockerfile still
runs in any build, and those two are the ones that do not.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(COMPONENT / "docker" / "editor"))
import editor_plan  # noqa: E402

runner_plan = editor_plan.runner_plan
prime_contract = editor_plan.prime_contract

#: The version of this document's shape. ⛔ A consumer refuses one it has not read.
BUILDS_API = 1

#: The four builds, and the Dockerfile target each one names.
TARGETS = {"runner": "runner", "editor": "editor", "runner-prime": "runner-prime", "editor-prime": "editor-prime"}

#: The course layers' Dockerfile, and the roots its context reads.
LAYER_DOCKERFILE = "docker/prime/Dockerfile"
LAYER_INPUTS = ("docker/prime", "prime")

#: Read by every build's context and in no inputs digest.
CONTEXT_ONLY = (".dockerignore",)

#: The runner's warmers: an input of a PRIMED runner only (`docker/minimal/build.py`).
WARMERS = "prime"

#: What `build.py` proves in a real session before it tags an editor.
EDITOR_PROOFS = ["python3 docker/editor/activation.py <image>", "python3 docker/editor/confinement.py <image>"]


class Refused(ValueError):
    """A build this component will not describe, and why."""


def _read_prime(prime) -> prime_contract.Prime | None:
    """The prime at `prime`, read for its shape, or `None` when there is none."""
    return prime_contract.read(prime) if prime is not None else None


def _runner(root: Path, names, platform: str, prime=None) -> runner_plan.Plan:
    pins = runner_plan.load(root)
    names = editor_plan.selection(pins, names)
    roots = runner_plan.INPUT_ROOTS if prime is None else runner_plan.INPUT_ROOTS + (WARMERS,)
    built = runner_plan.plan(pins, names, platform, runner_plan.inputs_digest(root, roots), prime)
    if prime is not None:
        prime_contract.guard(prime, pins, built.names)
    return built


def _editor(root: Path, names, platform: str, prime=None) -> editor_plan.EditorPlan:
    pins = runner_plan.load(root)
    runner = _runner(root, names, platform)
    return editor_plan.plan(pins, editor_plan.load(root), runner, editor_plan.inputs_digest(root), prime)


def _images(args: dict[str, str]) -> dict[str, str]:
    """Every ARG a `FROM ${...}` reads: the one naming rule both Dockerfiles keep."""
    return {key: value for key, value in sorted(args.items()) if key.endswith(("_IMAGE", "_BASE"))}


def layer(root: Path, image: str, names, platform: str, prime) -> tuple[str, dict[str, str]]:
    """The course layer's tag and ARGs: `image`'s unprimed tag, warmed with `prime`."""
    if prime is None:
        raise Refused("a course layer warms a prime, and none was given: pass --prime DIR")
    runner = _runner(root, names, platform)
    prime_contract.guard(prime, runner_plan.load(root), runner.names)
    base = runner.tag if image == "runner" else _editor(root, names, platform).tag
    args = {"BASE_IMAGE": base, **runner_plan.primed(prime), "PRIME_KEY": prime.digest}
    folded = hashlib.sha256(
        f"{runner_plan.inputs_digest(root, LAYER_INPUTS)}\0{prime.digest}".encode()
    ).hexdigest()
    return f"{base}-prime-{folded[:12]}", args


def described(root: Path, image: str, names, platform: str, prime=None) -> dict:
    """The build `image` is, as data. Raises `Refused`, or a plan's own refusal."""
    if image not in TARGETS:
        raise Refused(f"no build is named {image!r}; the builds are {sorted(TARGETS)}")
    root, read = Path(root), _read_prime(prime)
    if image == "runner":
        built = _runner(root, names, platform, read)
        tag, args, dockerfile = built.tag, built.build_args, runner_plan.DOCKERFILE
        inputs = runner_plan.INPUT_ROOTS + ((WARMERS,) if read else ())
        here = {}
    elif image == "editor":
        built = _editor(root, names, platform, read)
        tag, args, dockerfile = built.tag, built.build_args, editor_plan.DOCKERFILE
        inputs = runner_plan.INPUT_ROOTS + editor_plan.OWN_INPUTS
        here = {"RUNNER_IMAGE": "runner"}
    else:
        tag, args = layer(root, image.split("-")[0], names, platform, read)
        dockerfile, inputs = LAYER_DOCKERFILE, LAYER_INPUTS
        here = {"BASE_IMAGE": image.split("-")[0]}
    return {
        "builds_api": BUILDS_API,
        "image": image,
        "context": ".",
        "dockerfile": dockerfile,
        "target": TARGETS[image],
        "platform": platform,
        "tag": tag,
        "args": dict(sorted(args.items())),
        "from": _images(args),
        "built_here": here,
        "contexts": {"consumer-prime": "prime" if read is not None else "empty"},
        "inputs": sorted(set(inputs) | set(CONTEXT_ONLY)),
        "proved_by": EDITOR_PROOFS if image == "editor" else [],
    }


def host_platform() -> str:
    """This machine's platform, as the runner's build names it."""
    sys.path.insert(0, str(COMPONENT / "docker" / "minimal"))
    import build as runner_build  # noqa: PLC0415

    return runner_build.host_platform()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", choices=sorted(TARGETS))
    parser.add_argument("--runtimes", required=True, help="the declared set, comma-separated")
    parser.add_argument("--prime", default=None, help="a consumer's prime directory")
    parser.add_argument("--platform", default=None)
    parser.add_argument("--root", default=str(COMPONENT))
    args = parser.parse_args(argv)
    names = [name for name in args.runtimes.split(",") if name]
    try:
        document = described(Path(args.root).resolve(), args.image, names, args.platform or host_platform(),
                             Path(args.prime) if args.prime else None)
    except (Refused, runner_plan.Refused, prime_contract.Refused) as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 2
    print(json.dumps(document, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
