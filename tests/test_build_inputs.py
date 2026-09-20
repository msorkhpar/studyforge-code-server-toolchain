"""The one copy of the build's inputs (`W391`) — every clause BOTH ways.

No Docker needed. Run from the component root:
`python3 -m unittest discover -s tests -v`.

⛔ `TC-04/3`: the modules that plant a defect each kept their own list of the
directories to copy, so `lockdown/` had to be added to each of them by hand.
⭐ What settles it is asserted here: the list is DERIVED from the plans' own
declarations, and a new top-level input directory is ONE edit — in the plan
that declares it — after which every planted copy carries it.
"""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "docker" / "editor"))

import build_inputs  # noqa: E402
import editor_plan  # noqa: E402

runner_plan = editor_plan.runner_plan
#: `shutil.copy…(ROOT / <one name>, …)` — a module copying a top-level input
#: out of the tree itself, which is the duplication this row removed.
COPY_FROM_ROOT = re.compile(r"shutil\.copy(tree)?\(\s*ROOT\s*/\s*([^,]+),")


def own_copies(text: str) -> list[str]:
    """Every source in `text` that re-lists the build's inputs instead of reading the helper.

    ⭐ Three shapes are a second list, and the row is about the LIST: a whole
    input directory copied out of the tree, a name that is not a literal
    (which is how a list hides in a loop), and more than one named input file
    in the same module. ⚠️ A deeper path (`ROOT / "docker" / "minimal" /
    "smoke"`) is a fixture INSIDE an input, not the input; and ONE named file
    is a restore, not a list — `tests/test_editor_plan.py` puts the real
    `editor-pins.json` back over a planted one that way.
    """
    found, files = [], []
    for match in COPY_FROM_ROOT.finditer(text):
        source = match.group(2).strip()
        if "/" in source:
            continue
        literal = source.strip("\"'")
        if literal == source:
            found.append(source)
        elif literal in build_inputs.entries():
            (found if match.group(1) else files).append(source)
    return found + (files if len(files) > 1 else [])


class TheEntries(unittest.TestCase):
    """The names a copy carries are derived from the plans, never listed twice."""

    def test_every_declared_input_reaches_the_copy_through_its_top_level_name(self):
        entries = build_inputs.entries()
        for entry in build_inputs.declared():
            with self.subTest(declared=entry):
                self.assertIn(Path(entry).parts[0], entries)
        self.assertIn(".dockerignore", entries)

    def test_the_two_plans_under_one_docker_directory_are_copied_once(self):
        self.assertIn("docker/minimal", runner_plan.INPUT_ROOTS)
        self.assertIn("docker/editor", editor_plan.OWN_INPUTS)
        self.assertEqual(build_inputs.entries().count("docker"), 1)

    def test_a_plans_own_declaration_narrows_the_copy_to_it(self):
        runner_only = build_inputs.entries(runner_plan.INPUT_ROOTS)
        self.assertIn("pins.json", runner_only)
        for editor_own in ("editor-pins.json", "prime", editor_plan.LOCKDOWN):
            with self.subTest(absent=editor_own):
                self.assertNotIn(editor_own, runner_only)
                self.assertIn(editor_own, build_inputs.entries())


class TheCopy(unittest.TestCase):
    """What lands on disk: every input, nothing of the tree touched."""

    def test_the_copy_carries_every_input_and_both_digests_are_the_trees(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_inputs.copy_inputs(tmp)
            for entry in build_inputs.entries():
                with self.subTest(entry=entry):
                    self.assertTrue((root / entry).exists())
            self.assertEqual(runner_plan.inputs_digest(root), runner_plan.inputs_digest(ROOT))
            self.assertEqual(editor_plan.inputs_digest(root), editor_plan.inputs_digest(ROOT))
            self.assertEqual(sorted(p.name for p in root.rglob("__pycache__")), [])

    def test_a_runner_only_copy_carries_the_runners_inputs_and_not_the_editors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_inputs.copy_inputs(tmp, inputs=runner_plan.INPUT_ROOTS)
            self.assertEqual(runner_plan.inputs_digest(root), runner_plan.inputs_digest(ROOT))
            self.assertFalse((root / "prime").exists())
            self.assertFalse((root / editor_plan.LOCKDOWN).exists())

    def test_the_target_is_replaced_and_the_source_tree_is_never_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "context"
            target.mkdir()
            (target / "stale.txt").write_text("from an earlier plant", encoding="utf-8")
            before = editor_plan.inputs_digest(ROOT)
            build_inputs.copy_inputs(target)
            self.assertFalse((target / "stale.txt").exists())
            self.assertEqual(editor_plan.inputs_digest(ROOT), before)


class TheOneEdit(unittest.TestCase):
    """⭐ The row's second clause: a new input directory is ONE edit."""

    def test_a_new_top_level_input_directory_is_declared_once_and_every_copy_carries_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = build_inputs.copy_inputs(Path(tmp) / "source")
            (source / "extra").mkdir()
            (source / "extra" / "carried.txt").write_text("a new input\n", encoding="utf-8")

            undeclared = build_inputs.copy_inputs(Path(tmp) / "undeclared", source)
            self.assertFalse((undeclared / "extra").exists())

            declared = editor_plan.OWN_INPUTS + ("extra",)
            with mock.patch.object(editor_plan, "OWN_INPUTS", declared):
                after = build_inputs.copy_inputs(Path(tmp) / "declared", source)
            self.assertEqual((after / "extra" / "carried.txt").read_text(encoding="utf-8"), "a new input\n")

    def test_the_new_directory_is_declared_in_the_plan_and_in_no_test_module(self):
        """The edit is the plan's; no module names the directories a second time."""
        with mock.patch.object(editor_plan, "OWN_INPUTS", editor_plan.OWN_INPUTS + ("extra",)):
            self.assertIn("extra", build_inputs.entries())
        self.assertNotIn("extra", build_inputs.entries())


class TheHelperLivesOnce(unittest.TestCase):
    """⭐ The row's first clause, read off the modules themselves."""

    def test_no_test_module_copies_a_top_level_build_input_out_of_the_tree(self):
        """⚠️ This module is excluded: the planted shapes below are its subject, in strings."""
        for module in sorted(Path(__file__).parent.glob("test_*.py")):
            if module.name == Path(__file__).name:
                continue
            with self.subTest(module=module.name):
                self.assertEqual(own_copies(module.read_text(encoding="utf-8")), [])

    def test_every_module_that_plants_a_copy_reads_the_one_helper(self):
        planters = []
        for module in sorted(Path(__file__).parent.glob("test_*.py")):
            text = module.read_text(encoding="utf-8")
            if "build_inputs.copy_inputs(" in text:
                planters.append(module.name)
                with self.subTest(module=module.name):
                    self.assertIn("import build_inputs", text)
        self.assertGreater(len(planters), 1)

    def test_the_reading_catches_a_planted_second_list_and_passes_what_is_not_one(self):
        planted = [
            '    shutil.copytree(ROOT / "prime", target / "prime")\n',
            "    for folder in FOLDERS:\n        shutil.copytree(ROOT / folder, root / folder)\n",
            "    for name in NAMES:\n        shutil.copy(ROOT / name, root / name)\n",
            '    shutil.copy(ROOT / "pins.json", r / "pins.json")\n'
            '    shutil.copy(ROOT / "editor-pins.json", r / "editor-pins.json")\n',
        ]
        for text in planted:
            with self.subTest(planted=text.split("\n")[0].strip()):
                self.assertNotEqual(own_copies(text), [])
        allowed = [
            '    shutil.copytree(ROOT / "docker" / "minimal" / "smoke" / "node", work)\n',
            '    shutil.copy(SOURCE / "extension.js", root / "extension.js")\n',
            '    shutil.copy(ROOT / "editor-pins.json", root / "editor-pins.json")\n',
        ]
        for text in allowed:
            with self.subTest(allowed=text.strip()):
                self.assertEqual(own_copies(text), [])


if __name__ == "__main__":
    unittest.main()
