"""Tag an image this component builds for a registry namespace, and push it only when asked.

**What it does.** Plans the runner's or the editor's build exactly as their own
`build.py` does, takes the tag that plan computes, and names the image
`<namespace>/<published name>:<that tag>`, where the published name is
`studyforge-code-toolchain-runner` or `studyforge-code-toolchain-editor`. It then runs the build, `docker tag`, and,
with `--push`, `docker push`. ⭐ The tag is never written by hand: it is the
plan's, so the name a registry holds says which inputs built it.

**How you use it.** From the component root, with the namespace in the
environment and a login already done by you (this script never logs in):

    export TOOLCHAIN_NAMESPACE=<your registry namespace>
    python3 docker/publish.py editor --runtimes java,maven --dry-run
    python3 docker/publish.py runner --runtimes java,maven          # build and tag locally
    python3 docker/publish.py runner --runtimes java,maven --push   # and push

`--dry-run` prints the exact commands and runs none of them, so it needs no
Docker. `--prime DIR` and `--platform` are handed to the build unchanged.

⛔ **The namespace comes from `TOOLCHAIN_NAMESPACE` and from nowhere else**: no
flag, no default, no literal in this repository. With it unset or empty the
script refuses before it plans anything. ⭐ A consumer pins the pushed image by
DIGEST (`docker push` prints it), because a digest names one image for good.

**Depends on.** The standard library, the two build scripts and their plans,
and a Docker CLI when it is not a dry run.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPONENT = HERE.parent
sys.path.insert(0, str(HERE / "editor"))
sys.path.insert(0, str(HERE / "minimal"))
import build as runner_build  # noqa: E402
import editor_plan  # noqa: E402

#: The one place the namespace is read from.
NAMESPACE_VARIABLE = "TOOLCHAIN_NAMESPACE"

#: What a registry namespace may look like: lower-case path parts, with an optional host and port first.
NAMESPACE = re.compile(r"^[a-z0-9]+(?:[._:-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$")

#: The image each name builds, and the build script that builds it.
BUILDS = {"runner": HERE / "minimal" / "build.py", "editor": HERE / "editor" / "build.py"}

#: The name a registry sees for each image. It is not the local repository's last part: the local build
#: names stay as they are, and only the published name is prefixed so that it says what the image belongs to.
PUBLISHED = {"runner": "studyforge-code-toolchain-runner", "editor": "studyforge-code-toolchain-editor"}


class Refused(ValueError):
    """A publish that will not start, and why."""


def namespace(env) -> str:
    """The registry namespace from the environment, or `Refused`."""
    value = (env.get(NAMESPACE_VARIABLE) or "").strip()
    if not value:
        raise Refused(f"{NAMESPACE_VARIABLE} is not set; export it (login is yours, outside this script)")
    if not NAMESPACE.match(value):
        raise Refused(f"{NAMESPACE_VARIABLE} is not a registry namespace: lower-case letters, digits and . _ - /")
    return value


def local_tag(root: Path, image: str, platform: str, names, prime: Path | None) -> str:
    """The tag the image's own build computes for this checkout, before any Docker is touched."""
    if image == "editor":
        return editor_build_planned(root, platform, names, prime)
    return runner_build.planned(root, platform, names, prime).tag


def editor_build_planned(root: Path, platform: str, names, prime: Path | None) -> str:
    runner = editor_plan.runner_plan
    pins = runner.load(root)
    runner_built = runner.plan(pins, editor_plan.selection(pins, names), platform, runner.inputs_digest(root))
    read = editor_plan.prime_contract.read(prime) if prime is not None else None
    return editor_plan.plan(pins, editor_plan.load(root), runner_built, editor_plan.inputs_digest(root), read).tag


def reference(local: str, space: str, image: str) -> str:
    """`<namespace>/<published name>:<tag>` for a local tag `<repository>/<image>:<tag>`."""
    tag = local.rsplit(":", 1)[1]
    return f"{space}/{PUBLISHED[image]}:{tag}"


def commands(image: str, local: str, remote: str, names, platform: str | None, prime: Path | None,
             push: bool) -> list[list[str]]:
    build = ["python3", str(BUILDS[image].relative_to(COMPONENT)), "--runtimes", ",".join(names)]
    build += ["--platform", platform] if platform else []
    build += ["--prime", str(prime)] if prime else []
    steps = [build, ["docker", "tag", local, remote]]
    return steps + ([["docker", "push", remote]] if push else [])


def main(argv: list[str], env=None, run=subprocess.run, out=sys.stdout) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", choices=sorted(BUILDS))
    parser.add_argument("--runtimes", default=",".join(editor_plan.DEFAULT_SET),
                        help="the declared set, comma-separated (default: %(default)s)")
    parser.add_argument("--platform", default=None)
    parser.add_argument("--prime", default=None, help="a consumer's prime directory, handed to the build")
    parser.add_argument("--push", action="store_true", help="push the tag; without it nothing leaves this host")
    parser.add_argument("--dry-run", action="store_true", help="print the commands and run none of them")
    args = parser.parse_args(argv)

    try:
        space = namespace(os.environ if env is None else env)
        names = [name for name in args.runtimes.split(",") if name]
        prime = Path(args.prime).resolve() if args.prime else None
        local = local_tag(COMPONENT, args.image, args.platform or runner_build.host_platform(), names, prime)
    except (Refused, runner_build.planning.Refused, editor_plan.Refused) as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 2
    remote = reference(local, space, args.image)
    steps = commands(args.image, local, remote, names, args.platform, prime, args.push)
    for step in steps:
        print(shlex.join(step), file=out)
        if not args.dry_run:
            completed = run(step, stdin=subprocess.DEVNULL)
            if completed.returncode != 0:
                return completed.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
