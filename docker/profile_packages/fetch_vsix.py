"""Fetch one editor extension archive (.vsix) and refuse it unless its sha256 is the pinned one.

    python3 fetch_vsix.py <url> <destination file> <sha256>

Only the recipe's fetch stage runs it, the one stage with a network. ⛔ No checksum is fetched: the
value checked against is the one recorded in the profile. ⛔ The request carries a placeholder
User-Agent and no identity and no credentials. Standard library only.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

USER_AGENT = "Example/0.1 (+https://example.invalid)"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: fetch_vsix.py <url> <destination file> <sha256>", file=sys.stderr)
        return 2
    url, destination, pinned = argv
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as answer:
        data = answer.read()
    actual = hashlib.sha256(data).hexdigest()
    if actual != pinned:
        print(f"editor-extension archive {url}: sha256 {actual}, but the profile pins {pinned}", file=sys.stderr)
        return 1
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    Path(destination).write_bytes(data)
    print(f"fetched {len(data)} bytes, sha256 {actual}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
