"""The files of a consumer's prime that the build takes in, and the digest over exactly those.

**What it does.** Inside a git work tree, a file git ignores (`build/`, `.gradle/`,
`target/`, any local output) is not part of the prime: it is not in the digest
that moves the course layer's tag, and `stage` hands the build a context
without it, so the image holds what the digest covered. Outside a work tree, or
with no git, every file counts, exactly as `prime/prime.py`'s own digest does.
Tracked files and untracked-but-not-ignored files both count, so an edit moves
the tag before it is committed.

**How you use it.** `read(DIR)` is `prime.read` with the digest replaced; for the
context the consumer builds with:

    python3 consuming/prime_files.py DIR DEST

prints `DIR` when nothing in it is ignored, else copies the kept files to
`DEST` and prints `DEST`. ⭐ Over a prime with nothing ignored the digest is
byte-for-byte `prime.digest`, so no published tag moves.

**Depends on.** The standard library, `prime/prime.py`, and `git` when present.
Lives beside `builds.py`, outside every hashed input root, so adding it moves no tag.
"""

from __future__ import annotations

import dataclasses
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(COMPONENT / "prime"))
import prime as prime_contract  # noqa: E402


def _all(root: Path) -> list[Path]:
    return sorted((p.relative_to(root) for p in root.rglob("*") if p.is_file()), key=Path.as_posix)


def files(root) -> list[Path]:
    """The prime's files relative to `root`, sorted by posix path, minus those git ignores."""
    root = Path(root)
    everything = _all(root)
    try:
        listed = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
                                 "--exclude-standard"], stdin=subprocess.DEVNULL, capture_output=True)
    except OSError:
        return everything
    if listed.returncode != 0:
        return everything
    kept = {Path(name.decode("utf-8", "surrogateescape")) for name in listed.stdout.split(b"\0") if name}
    return [path for path in everything if path in kept]


def digest(root) -> str:
    """`prime.digest`'s bytes over `files(root)`: identical when nothing is ignored."""
    root = Path(root)
    hashed = hashlib.sha256(b"prime\0")
    for relative in files(root):
        hashed.update(relative.as_posix().encode() + b"\0" + (root / relative).read_bytes() + b"\0")
    return hashed.hexdigest()


def read(directory) -> "prime_contract.Prime":
    """`prime.read(directory)` with the digest taken over the kept files only."""
    return dataclasses.replace(prime_contract.read(directory), digest=digest(directory))


def stage(root, work) -> Path:
    """The directory to hand the build as `consumer-prime`: `root`, or a copy of its kept files in `work`."""
    root, work = Path(root), Path(work)
    kept = files(root)
    if len(kept) == len(_all(root)):
        return root
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    for relative in kept:
        (work / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, work / relative)
    return work


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: prime_files.py PRIME_DIR STAGE_DIR")
    print(stage(sys.argv[1], sys.argv[2]))
