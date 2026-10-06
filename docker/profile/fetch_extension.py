"""Fetch a profile's `editor-extension` archives, refuse any whose sha256 is not the pinned one, unpack them.

**What it does.** Reads lines `<id>|<url>|<sha256>|<strip>` (from `profile_plan.py`, out of
`profiles/<name>.json`), downloads each archive, and exits non-zero naming the first entry whose
bytes do not hash to the pinned value. A good archive (`.zip`, `.tar.gz` or `.tgz`) is unpacked
into `<output>/<id>/`, with the file modes the archive records, without its first `<strip>` path
components (a JDK archive's one top directory, for instance).

**How you use it.** Only inside the recipe's `fetch` stage:

    python3 fetch_extension.py <lines text> <output directory>

⛔ No checksum is fetched: the value checked against is the one recorded in the profile. ⛔ The
request carries a placeholder User-Agent and no identity and no credentials. No lines, no work.

**Depends on.** The standard library only.
"""

from __future__ import annotations

import hashlib
import io
import os
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

USER_AGENT = "Example/0.1 (+https://example.invalid)"


def parse(text: str) -> list[tuple[str, str, str, int]]:
    """The non-empty lines, each split into (id, url, sha256, strip); `strip` is 0 when a line has three fields."""
    entries = []
    for line in text.splitlines():
        if line.strip():
            name, url, sha256, *strip = line.strip().split("|")
            entries.append((name, url, sha256, int(strip[0]) if strip else 0))
    return entries


def check(name: str, data: bytes, sha256: str) -> str | None:
    """None when the bytes are the pinned ones; otherwise what is wrong, naming the entry."""
    actual = hashlib.sha256(data).hexdigest()
    if actual != sha256:
        return f"editor-extension {name!r}: the archive has sha256 {actual}, but the profile pins {sha256}"
    return None


def _stripped(name: str, strip: int) -> str | None:
    """`name` without its first `strip` components; None for an entry that is only those components."""
    parts = [part for part in name.split("/") if part not in ("", ".")]
    return "/".join(parts[strip:]) or None


def unpack(data: bytes, target: Path, strip: int = 0, kind: str = "zip") -> None:
    """Unpack the archive under `target`, refusing a member that would land outside it, keeping modes."""
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()

    def place(name: str) -> Path:
        destination = (root / name).resolve()
        if root != destination and root not in destination.parents:
            raise ValueError(f"{name!r} is outside the archive's directory")
        return destination

    if kind == "tar":
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            for member in archive.getmembers():
                name = _stripped(member.name, strip)
                if name is None:
                    continue
                destination = place(name)
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                elif member.issym():
                    # A link's target must stay inside the archive's directory too.
                    place(os.path.normpath(os.path.join(os.path.dirname(name), member.linkname)))
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.symlink_to(member.linkname)
                elif member.isfile():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.extractfile(member).read())
                    destination.chmod(member.mode & 0o777 or 0o644)
        return
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            name = _stripped(member.filename, strip)
            if name is None:
                continue
            destination = place(name)
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(member))
            destination.chmod((member.external_attr >> 16) & 0o777 or 0o644)


def kind_of(url: str) -> str:
    """`tar` for a `.tar.gz` or `.tgz` address, `zip` otherwise."""
    return "tar" if url.endswith((".tar.gz", ".tgz")) else "zip"


def main(argv: list[str]) -> int:
    text, out = argv[0], Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for name, url, sha256, strip in parse(text):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=600) as response:
            data = response.read()
        problem = check(name, data, sha256)
        if problem:
            print(problem, file=sys.stderr)
            return 1
        unpack(data, out / name, strip, kind_of(url))
        print(f"editor-extension {name!r}: {len(data)} bytes, sha256 {sha256}, unpacked")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
