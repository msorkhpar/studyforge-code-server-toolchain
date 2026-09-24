"""No tracked file cites a rule, a spec section, a work item or a commit: each states its reason.

Run from the component root: `python3 -m unittest tests.test_no_citations -v`.

⭐ **Why.** This component is read on its own: its README says nothing outside
it is needed. A rule id (`R1` to `R21`), a section of a spec kept elsewhere
(`§` and a number), a work item's id or a commit is a pointer a reader of this
repository can resolve nowhere, so a file says the reason itself instead.

**What is read.** Every tracked text file, whole; for a test module, only its
docstrings and comments, because a test's string literals are its data and a
test of an id's grammar has to spell one. ⛔ `NOT_READ` names the files that
are not read, each with its reason. ⭐ The rendered compose reference is read
here as a tracked file, and `render` is also read directly, since a consumer's
own compose file is rendered from the same text.

Standard library only, plus `git`.
"""

from __future__ import annotations

import ast
import io
import json
import re
import subprocess
import sys
import tokenize
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "consuming"))

import consuming  # noqa: E402

#: A work item's id, a milestone or an epic.
ROADMAP = re.compile(
    r"\b(?:W[0-9]{1,4}[a-z]?|(?:AX|EX|FND|JS|NS|OPS|QA|REL|SF|SK|TC|INT|ISO|PO|CTO)-[0-9]{1,3}[a-z]?)"
    r"(?:/[0-9]+)?\b|\bM[0-9]{1,2}\b|\bE[01][0-9]\b"
)

#: A spec rule's id, `R1` to `R21`.
RULE_ID = re.compile(r"\bR(?:[1-9]|1[0-9]|2[01])\b")

#: A section of a spec, written with its sign.
SECTION = re.compile(r"§\s?[0-9]")

#: A commit, abbreviated or whole: a hex word with a letter and a digit, standing alone. A tag's
#: hash (`…-amd64-0123456789ab`) and a digest (`sha256:…`) are joined to their name, so neither is one.
COMMIT = re.compile(r"(?<![\w./:@=-])(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}(?![\w-])")

#: What each pattern is, as a finding names it.
PATTERNS = (("a work item", ROADMAP), ("a rule id", RULE_ID), ("a spec section", SECTION), ("a commit", COMMIT))

#: Files this sweep does not read, each with its reason.
NOT_READ = {
    "pins.json": "pinned versions and checksums, where `5.11.0-M2` is a release name",
    "editor-pins.json": "pinned versions and checksums, data that no person wrote as prose",
    "tests/test_no_citations.py": "this module spells every pattern it looks for",
}


def tracked() -> list[str]:
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True)
    return sorted(name for name in listed.stdout.split("\0") if name)


def prose_of_python(text: str) -> str:
    """A module's docstrings and comments, each on its own line number, and nothing else.

    ⭐ What a test module SAYS rather than what it tests with: every other line
    is left empty, so a finding still names the line it is on.
    """
    lines = [""] * (len(text.splitlines()) + 1)
    for node in ast.walk(ast.parse(text)):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and body \
                and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            for number in range(body[0].lineno, body[0].end_lineno + 1):
                lines[number - 1] = text.splitlines()[number - 1]
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.COMMENT:
            lines[token.start[0] - 1] += " " + token.string
    return "\n".join(lines)


def read(name: str) -> str | None:
    """What the sweep reads of one tracked file, or `None` for one that is not text."""
    try:
        text = (ROOT / name).read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        return None
    if name.startswith("tests/") and name.endswith(".py"):
        return prose_of_python(text)
    return text


def citations(name: str, text: str) -> list[str]:
    """One finding per line of `text` that cites something, naming the file, the line and what."""
    return [f"{name}:{number}: {what}"
            for number, line in enumerate(text.splitlines(), start=1)
            for what, pattern in PATTERNS if pattern.search(line)]


class NoCitation(unittest.TestCase):
    def test_no_tracked_file_cites_a_rule_a_section_or_a_work_item(self):
        names = [name for name in tracked() if name not in NOT_READ]
        self.assertGreater(len(names), 40, "the sweep reads almost nothing, so it proves nothing")
        found = [finding for name in names if (text := read(name)) is not None
                 for finding in citations(name, text)]
        self.assertEqual(found, [])

    def test_the_rendered_compose_reference_carries_no_rule_id(self):
        contract = json.loads((ROOT / "consuming.json").read_text(encoding="utf-8"))
        rendered = consuming.render(contract)
        self.assertIn("docker", rendered.lower(), "the render is empty, so nothing was read")
        self.assertEqual(citations("render", rendered), [])

    def test_every_file_it_does_not_read_is_tracked(self):
        # ⭐ An exemption for a file that is gone would exempt its next namesake.
        self.assertEqual(sorted(set(NOT_READ) - set(tracked())), [])


class TheSweepCanFire(unittest.TestCase):
    """Each pattern is seen where it is prose, and a test's own data is not read."""

    def test_each_citation_is_seen(self):
        for line in ("a finding (R19)", "spec §8.3 says so", "as `W465` found", "`REL-13/3`", "in M9",
                     "the reading `c535074` took", "fixed at 326f591e"):
            with self.subTest(line=line):
                self.assertTrue(citations("x", line), line)

    def test_a_reason_and_a_version_string_are_not_citations(self):
        for line in ("no Docker socket reaches a serving process", "maven 3.9.11", "the runner's R&D",
                     "Ruby 3", "sha256 R2D2", "runner:java-maven-amd64-0123456789ab", "a face",
                     "sha256:97014c4b396021f9ddb7d592a7dbedb0c4e4215c29e03dc01c393558aefb71c2", "1234567"):
            with self.subTest(line=line):
                self.assertEqual(citations("x", line), [], line)

    def test_a_tests_string_literals_are_data_and_its_comments_are_prose(self):
        module = '"""Holds a rule."""\n\nCASES = ["R19", "W465"]  # read as (R5)\n'
        self.assertEqual(citations("t", prose_of_python(module)), ["t:3: a rule id"])


if __name__ == "__main__":
    unittest.main()
