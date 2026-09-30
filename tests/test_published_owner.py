"""A tracked file names the account that owns a repository only by the literal `<owner>`.

Run from the component root: `python3 -m unittest tests.test_published_owner -v`.

A clone instruction reads `https://github.com/<owner>/<repository-name>.git`,
where `<owner>` is written exactly so and the real account name is never in the
tree. This module reads every tracked text file and fails on a GitHub address of
one of this product's repositories, in the URL form or the ssh form, whose owner
is anything else.

Standard library only, plus `git`.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: A GitHub address of one of this product's repositories, owner captured.
ADDRESS = re.compile(r"github\.com[:/]+([^/\s\"'`()<>]+|<[^/\s>]*>)/studyforge[A-Za-z0-9._-]*")

#: The one owner a tracked file may write.
PLACEHOLDER = "<owner>"


def tracked(root: Path) -> list[str]:
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True, check=True)
    return sorted(name for name in listed.stdout.split("\0") if name)


def owners(root: Path) -> dict[str, list[str]]:
    """Each tracked file that gives one of these repositories a real-looking owner."""
    found: dict[str, list[str]] = {}
    for name in tracked(root):
        if name == "README.md":
            continue  # the root README may name its owner
        try:
            text = (root / name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        bad = sorted({m.group(1) for m in ADDRESS.finditer(text) if m.group(1) != PLACEHOLDER})
        if bad:
            found[name] = bad
    return found


def scratch(directory: str, files: dict[str, str]) -> Path:
    """A throwaway repository with `files` written and staged."""
    root = Path(directory)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    return root


class PublishedOwner(unittest.TestCase):
    def test_no_tracked_file_gives_a_repository_a_real_owner(self):
        self.assertGreater(len(tracked(ROOT)), 20, "the sweep read too few files to mean anything")
        self.assertEqual(owners(ROOT), {}, "write the owner as the literal placeholder")

    def test_a_planted_real_looking_owner_is_read_in_every_form(self):
        host = "github" + ".com"
        planted = {
            "NOTICE.md": f"git clone https://{host}/someone/studyforge.git\n",
            "docs/a.md": f"see https://{host}/someone/studyforge-narrate-service\n",
            "src/mod.py": f'URL = "git@{host}:someone/studyforge-code-server-toolchain.git"\n',
        }
        with tempfile.TemporaryDirectory() as directory:
            found = owners(scratch(directory, planted))
        self.assertEqual(sorted(found), sorted(planted))

    def test_the_placeholder_and_other_projects_are_not_flagged(self):
        host = "github" + ".com"
        planted = {
            "README.md": f"git clone https://{host}/<owner>/studyforge.git\n",
            "docs/a.md": f"a font from https://{host}/silnrsi/font-charis\n",
        }
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(owners(scratch(directory, planted)), {})

    def test_the_root_readme_may_name_its_owner(self):
        host = "github" + ".com"
        planted = {"README.md": f"git clone https://{host}/someone/studyforge.git\n"}
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(owners(scratch(directory, planted)), {})


if __name__ == "__main__":
    unittest.main()
