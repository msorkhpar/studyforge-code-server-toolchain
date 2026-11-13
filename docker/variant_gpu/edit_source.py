"""Apply a variant's exact-string edits to an unpacked source tree, checking every file before and after.

    python3 edit_source.py <edits.json> <source root>

Each edit is `{"file", "sha256", "after", "replace": [[old, new], ...]}`: `file` is relative to the source
root, `sha256` is the file's digest before the edit and `after` its digest once every pair is applied. Each
`old` must occur exactly once. A file that is not the pinned one, an `old` that is missing or repeated, or a
result that is not the pinned `after` stops the build, naming the file. Nothing is written until the result
matches.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def apply(edits: list[dict], root: Path) -> list[str]:
    done = []
    for edit in edits:
        path = root / edit["file"]
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != edit["sha256"]:
            raise SystemExit(f"edit_source: {edit['file']} is not the pinned file (sha256 {hashlib.sha256(data).hexdigest()})")
        text = data.decode("utf-8")
        for old, new in edit["replace"]:
            if text.count(old) != 1:
                raise SystemExit(f"edit_source: {edit['file']}: the text to replace occurs {text.count(old)} times, not once")
            text = text.replace(old, new)
        result = text.encode("utf-8")
        if hashlib.sha256(result).hexdigest() != edit["after"]:
            raise SystemExit(f"edit_source: {edit['file']}: the edited file has sha256 {hashlib.sha256(result).hexdigest()}, "
                             f"not the pinned {edit['after']}")
        path.write_bytes(result)
        done.append(edit["file"])
    return done


def main(argv: list[str]) -> int:
    edits = json.loads(Path(argv[0]).read_text(encoding="utf-8"))["edits"]
    for name in apply(edits, Path(argv[1])):
        print(f"edit_source: {name} edited and checked")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
