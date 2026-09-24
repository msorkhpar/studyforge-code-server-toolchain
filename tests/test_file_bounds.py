"""This component's source files stay under the file-size bound (R11).

Run from the component root: `python3 -m unittest tests.test_file_bounds -v`.

⛔ **No source file over 400 lines, and no test over 600**, unless the module's
own docstring justifies it. ⭐ This reads every source file of the component:
each `.py`, `.js` and `.sh` and each Dockerfile outside `tests/`, and every
test module. Two files were split to meet it: `docker/editor/confinement.py`
(the session both gate halves open moved to `probe.py`) and
`consuming/consuming.py` (the compose text moved to `compose.py`). Data --
the generated keybindings seed, the pins, the fixtures -- is not a module and
is not read here.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_BOUND = 400
TEST_BOUND = 600
#: Files over the bound, by path, and the sentence their own header justifies it with.
JUSTIFIED = {"docker/editor/Dockerfile": "OVER THE 400-LINE BOUND, AND JUSTIFIED HERE (R11)"}


def lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def sources() -> list[Path]:
    """Every source file outside `tests/`, `__pycache__` and hidden directories."""
    return sorted(path for path in ROOT.rglob("*")
                  if path.is_file() and (path.suffix in {".py", ".js", ".sh"} or path.name == "Dockerfile")
                  and not {"tests", "__pycache__", ".git", ".work"} & set(path.relative_to(ROOT).parts)
                  and not path.relative_to(ROOT).parts[0].startswith("."))


class TheBound(unittest.TestCase):
    def test_it_reads_the_modules_it_names(self):
        names = {path.relative_to(ROOT).as_posix() for path in sources()}
        for expected in ("docker/editor/confinement.py", "docker/editor/probe.py", "docker/editor/Dockerfile",
                         "consuming/consuming.py", "consuming/compose.py", "lockdown/extension.js",
                         "docker/minimal/plan.py"):
            self.assertIn(expected, names)

    def test_no_source_file_is_over_the_bound(self):
        for path in sources():
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
