"""The `claude-sdks` profile stub: it plans, computes its tag, and refuses to build until pinned.

Run from the component root: `python3 -m unittest tests.test_profile_claude_sdks -v`.

Held: the profile layers on the course's base set (composition of existing pins), its tag has the
profile form, a build is refused by entry name while any entry reads TO-BE-PINNED, a runtime
outside the base set is refused by name, and adding the profile file moves no base tag and no
other profile's tag.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "docker" / "profile"))

import profile_build  # noqa: E402
import profile_plan  # noqa: E402
import test_profile as shared  # noqa: E402

NAME = "claude-sdks"
SET = ("python", "node", "java", "gradle", "kotlin")
AMD64, ARM64 = shared.AMD64, shared.ARM64
DIGEST = shared.IMAGE_DIGEST


class TheStubPlans(unittest.TestCase):
    def test_it_layers_on_the_course_base_set_and_names_both_images(self):
        profile = profile_plan.load(ROOT, NAME)
        self.assertEqual(profile["layers_on"], list(SET))
        self.assertEqual(profile["images"], ["runner", "editor"])
        self.assertEqual(len(profile["adds"]), 3)

    def test_the_tag_has_the_profile_form_for_both_images(self):
        runner = profile_plan.plan(ROOT, NAME, "runner", [], AMD64)
        editor = profile_plan.plan(ROOT, NAME, "editor", [], ARM64)
        self.assertRegex(runner.tag, r"^code-server-toolchain/runner-claude-sdks:gradle-java-kotlin-node-python-amd64-[0-9a-f]{12}$")
        self.assertRegex(editor.tag, r"^code-server-toolchain/editor-claude-sdks:gradle-java-kotlin-node-python-arm64-[0-9a-f]{12}$")
        self.assertEqual(runner.published, "studyforge-code-toolchain-runner-claude-sdks")

    def test_the_base_is_the_existing_flows_tag_for_the_set(self):
        for image in ("runner", "editor"):
            built = profile_plan.plan(ROOT, NAME, image, list(SET), AMD64)
            self.assertEqual(built.base_tag, profile_plan.base_plan(ROOT, image, sorted(SET), AMD64).tag)

    def test_the_command_line_prints_the_tag_and_the_plan(self):
        import subprocess
        import json
        script = str(ROOT / "docker" / "profile" / "profile_build.py")
        for image in ("runner", "editor"):
            tag = subprocess.run([sys.executable, script, "--profile", NAME, "--image", image, "--platform", AMD64,
                                  "--print-tag"], capture_output=True, text=True, check=True).stdout.strip()
            plan = json.loads(subprocess.run([sys.executable, script, "--profile", NAME, "--image", image,
                                              "--platform", AMD64, "--print-plan"], capture_output=True, text=True,
                                             check=True).stdout)
            self.assertEqual(tag, plan["tag"])
            self.assertEqual(tag, profile_plan.plan(ROOT, NAME, image, [], AMD64).tag)


class TheRefusals(unittest.TestCase):
    def test_a_build_is_refused_naming_every_unpinned_entry(self):
        profile = profile_plan.load(ROOT, NAME)
        self.assertEqual(profile_plan.unpinned(profile), ["python-sdks", "node-sdks", "jvm-sdks"])
        self.assertEqual(profile_build.main(["--profile", NAME, "--image", "runner", "--base-digest", DIGEST]), 2)

    def test_a_set_missing_a_layered_runtime_is_refused_by_name(self):
        with self.assertRaises(profile_plan.Refused) as caught:
            profile_plan.plan(ROOT, NAME, "runner", ["python", "node", "java"], AMD64)
        self.assertIn("gradle", str(caught.exception))
        self.assertIn("kotlin", str(caught.exception))

    def test_a_profile_listing_a_runtime_outside_the_base_set_is_refused_by_name(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir=ROOT / ".work" if (ROOT / ".work").is_dir() else None) as tmp:
            root = shared.context(tmp)
            shared.edit_profile(root, NAME, lambda d: d["layers_on"].append("swift"))
            with self.assertRaises(profile_plan.Refused) as caught:
                profile_plan.plan(root, NAME, "runner", list(SET), AMD64)
            self.assertIn("swift", str(caught.exception))


class NothingElseMoves(unittest.TestCase):
    def test_the_profile_is_in_no_base_or_other_profiles_tag(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir=ROOT / ".work" if (ROOT / ".work").is_dir() else None) as tmp:
            root = shared.context(tmp)
            before_bases = shared.base_tags(root)
            other = profile_plan.plan(root, "jvm-frameworks", "runner", [], AMD64).tag
            shared.edit_profile(root, NAME, lambda d: d["adds"].append(
                {"kind": "dependency", "id": "extra", "coordinates": "TO-BE-PINNED", "sha256": "TO-BE-PINNED"}))
            self.assertEqual(shared.base_tags(root), before_bases)
            self.assertEqual(profile_plan.plan(root, "jvm-frameworks", "runner", [], AMD64).tag, other)


if __name__ == "__main__":
    unittest.main()
