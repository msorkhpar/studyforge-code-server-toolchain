"""The editor image's own modules stay under the file-size bound (R11).

Run from the component root: `python3 -m unittest tests.test_file_bounds -v`.

⛔ **No source file over 400 lines, and no test over 600**, unless the module's
own docstring justifies it. ⭐ This reads the bound for `docker/editor/`, the
editor image's build, its two gates and their session, because that is where
`confinement.py` reached the bound exactly and was split: the session both
gate halves open moved to `probe.py`. The generated keybindings seed under
`seed/` is data written by a tool, not a module, and is not read here.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDITOR = ROOT / "docker" / "editor"
SOURCE_BOUND = 400
TEST_BOUND = 600
#: Files over the bound, by path, and the sentence their own header justifies it with.
JUSTIFIED = {"docker/editor/Dockerfile": "OVER THE 400-LINE BOUND, AND JUSTIFIED HERE (R11)"}


def lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def editor_sources() -> list[Path]:
    return sorted(path for path in EDITOR.iterdir()
                  if path.is_file() and (path.suffix in {".py", ".js", ".sh"} or path.name == "Dockerfile"))


class TheBound(unittest.TestCase):
    def test_it_reads_the_modules_it_names(self):
        names = {path.name for path in editor_sources()}
        for expected in ("confinement.py", "probe.py", "activation.py", "Dockerfile"):
            self.assertIn(expected, names)

    def test_no_editor_source_file_is_over_the_bound(self):
        for path in editor_sources():
            with self.subTest(path=path.name):
                reason = JUSTIFIED.get(path.relative_to(ROOT).as_posix())
                if reason:
                    self.assertIn(reason, path.read_text(encoding="utf-8"), "a justified file states why")
                    continue
                self.assertLessEqual(lines(path), SOURCE_BOUND,
                                     f"{path.relative_to(ROOT)} is over {SOURCE_BOUND} lines; split it (R11)")

    def test_no_test_module_is_over_the_bound(self):
        for path in sorted((ROOT / "tests").glob("test_*.py")):
            with self.subTest(path=path.name):
                self.assertLessEqual(lines(path), TEST_BOUND,
                                     f"{path.relative_to(ROOT)} is over {TEST_BOUND} lines; split it (R11)")


if __name__ == "__main__":
    unittest.main()
