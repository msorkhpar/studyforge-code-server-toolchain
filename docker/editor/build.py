"""Build the editor image: the runner for the editor's set first, then code-server on it.

**What it does.** Reads `pins.json` and `editor-pins.json`, refuses (naming
it) a declared runtime that is not pinned and anything the editor needs that is
not pinned, computes the editor's tag, builds the runner for the declared set
with the runner's own build command (`docker/minimal/build.py`), and then runs
`docker build` on `docker/editor/Dockerfile` with every ARG it needs. No ARG
has a default, so this script is the only way that Dockerfile builds.

**How you use it.** From the component root:

    python3 docker/editor/build.py                            # DEFAULT_SET
    python3 docker/editor/build.py --runtimes java,maven
    python3 docker/editor/build.py --runtimes java,maven --print-tag
    python3 docker/editor/build.py --runtimes java,maven --prime path/to/prime

`--prime DIR` warms the image's caches from a consumer's prime directory
(the contract is `prime/prime.py`'s); it is mounted read-only into the build
as the named context `consumer-prime`, and its digest moves the tag. Without
it, the context is an empty directory and nothing is warmed.
`--root DIR` builds a different copy of the component (the tests plant a
defect in a temporary copy); `--platform` defaults to this machine's.

⛔ **The image is TAGGED only after TWO real sessions have been opened in it**,
and the build writes an image ID rather than a tag until both pass:

1. **its lockdown RUNS** (`activation.py`, `W432`) -- the extension host's log
   shows the extension activating AND the extension announcing that it ran;
2. **the practice frame is CONFINED** (`confinement.py`, `W433`) -- a headless
   browser presses `Ctrl+Shift+P`, `Ctrl+P`, `Ctrl+,`, `F5` and the rest at
   that session and nothing opens, while the editor's own find widget still
   opens and what is typed still reaches the file on disk.

⚠️ A build on a host with no browser is REFUSED, not waved through -- the
check the first of these replaced read the INSTALLED list, passed, and shipped
an image whose lockdown never loaded. ⭐ The second exists one level up for
the same reason: a check that reads the keybindings FILE cannot see what the
workbench allows.

**Depends on.** The standard library, `editor_plan.py`, `activation.py`,
`confinement.py` and `cdp.py` beside it, the runner's `build.py` and
`plan.py`, a Docker CLI with BuildKit, and a Chromium-family browser for both
proofs. ⛔ It never mounts a socket; the proofs run containers from OUTSIDE,
with the Docker CLI, like every other container this component starts.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "minimal"))
import activation  # noqa: E402
import build as runner_build  # noqa: E402
import confinement  # noqa: E402
import editor_plan  # noqa: E402

COMPONENT = Path(__file__).resolve().parents[2]


def planned(root: Path, platform: str, names=editor_plan.DEFAULT_SET, prime=None) -> editor_plan.EditorPlan:
    """The editor's plan for the declared set on `platform`, or `Refused` before Docker is touched."""
    runner = editor_plan.runner_plan
    pins = runner.load(root)
    runner_built = runner.plan(pins, editor_plan.selection(pins, names), platform, runner.inputs_digest(root))
    read = editor_plan.prime_contract.read(prime) if prime is not None else None
    return editor_plan.plan(pins, editor_plan.load(root), runner_built, editor_plan.inputs_digest(root), read)


def runner_command(root: Path, platform: str, names=editor_plan.DEFAULT_SET) -> list[str]:
    """The runner's own build for the editor's set: exactly the command its own `build.py` runs.

    ⭐ It once rebuilt the runner's final stage with `--no-cache-filter runner`
    (TC-01/13: a warm cache served one selection's layers to another). `W379`
    keyed that stage by the image's own tag, so a warm cache is now correct by
    construction, and the editor no longer pays for a rebuild (`W379/1`).
    """
    runner = editor_plan.runner_plan
    pins = runner.load(root)
    built = runner.plan(pins, editor_plan.selection(pins, names), platform, runner.inputs_digest(root))
    return runner_build.docker_command(root, built)


def docker_command(root: Path, built: editor_plan.EditorPlan, prime: Path, iidfile: Path | None = None) -> list[str]:
    """`docker build` for the editor, with `prime` as the read-only named context `consumer-prime`.

    ⛔ With an `iidfile` it takes NO `-t`: the build writes an image ID and the
    tag is applied afterwards, by `main`, and only once `activation.py` has
    seen the lockdown run in that image. ⭐ That is what makes *"an image whose
    lockdown did not load is not tagged"* a property of the tag rather than a
    sentence in a README (`W432`).
    """
    command = ["docker", "build", "--progress=plain", "--platform", built.platform,
               "-f", str(root / editor_plan.DOCKERFILE), "--target", "editor",
               *(["--iidfile", str(iidfile)] if iidfile else ["-t", built.tag]),
               "--build-context", f"consumer-prime={prime}"]
    for key in sorted(built.build_args):
        command += ["--build-arg", f"{key}={built.build_args[key]}"]
    return command + [str(root)]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runtimes", default=",".join(editor_plan.DEFAULT_SET),
                        help="the declared set, comma-separated (default: %(default)s)")
    parser.add_argument("--platform", default=None)
    parser.add_argument("--root", default=str(COMPONENT))
    parser.add_argument("--print-tag", action="store_true")
    parser.add_argument("--prime", default=None, help="a consumer's prime directory to warm the caches from")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    platform = args.platform or runner_build.host_platform()
    names = [name for name in args.runtimes.split(",") if name]
    prime = Path(args.prime).resolve() if args.prime else None
    try:
        built = planned(root, platform, names, prime)
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
        runner = subprocess.run(runner_command(root, platform, names), stdin=subprocess.DEVNULL)
        if runner.returncode != 0:
            return runner.returncode
    with tempfile.TemporaryDirectory(prefix="editor-build-") as work:
        built_id, empty = Path(work) / "image-id", Path(work) / "no-prime"
        empty.mkdir()
        completed = subprocess.run(docker_command(root, built, prime or empty, built_id), stdin=subprocess.DEVNULL)
        if completed.returncode != 0:
            return completed.returncode
        image = built_id.read_text(encoding="utf-8").strip()
        lock = editor_plan.lockdown_identity(root)
        try:
            proof = activation.prove(image, lock)
            confined = confinement.prove(image, lock) if proof.ok else None
        except (activation.Refused, confinement.cdp.CdpError) as refusal:
            print(f"refused: {refusal}", file=sys.stderr)
            return 2
    for failed in (proof, confined):
        if failed is not None and not failed.ok:
            print(f"refused: {failed.complaint()}", file=sys.stderr)
            print("the image was built and is NOT tagged; it is reachable only by its id "
                  f"{image}, and `docker image rm` takes it away", file=sys.stderr)
            return 1
    print(proof.activated.strip())
    print(confined.report)
    tagged = subprocess.run(["docker", "tag", image, built.tag], stdin=subprocess.DEVNULL)
    if tagged.returncode != 0:
        return tagged.returncode
    print(built.tag)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
