"""Every file an image or a POSIX shell reads is checked out with LF line ends.

Run from the component root: `python3 -m unittest tests.test_line_endings -v`.

⭐ **Why.** Git for Windows checks text out with CRLF line ends by default. The
entrypoint, the warm scripts and the Dockerfiles are copied into Linux images,
where `sh` reads a carriage return as part of each word and fails, and every
build input is hashed into an image tag, so a Windows checkout would compute
another tag from the same inputs. `.gitattributes` pins LF for every text file.

Standard library only, plus `git`; skipped where this is not a git checkout.
"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Files a Linux image or a POSIX shell reads as they are checked out.
LF_ONLY = (
    "docker/editor/Dockerfile",
    "docker/editor/entrypoint.sh",
    "docker/minimal/Dockerfile",
    "prime/warm-gradle.sh",
    "prime/warm-maven.sh",
    "pins.json",
)


class LineEndings(unittest.TestCase):
    def test_every_file_an_image_reads_is_checked_out_with_lf(self):
        git = shutil.which("git")
        if git is None:
            self.skipTest("git is not installed")
        done = subprocess.run([git, "check-attr", "text", "eol", "--", *LF_ONLY], cwd=ROOT,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True)
        if done.returncode != 0:
            self.skipTest("git cannot read this checkout's attributes here")
        said = {(path, key): value for path, key, value in
                (line.split(": ") for line in done.stdout.splitlines())}
        for path in LF_ONLY:
            with self.subTest(path=path):
                self.assertEqual(said[(path, "eol")], "lf", "checked out with the host's line ends")
                self.assertIn(said[(path, "text")], ("auto", "set"))


if __name__ == "__main__":
    unittest.main()
