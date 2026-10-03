"""The `claude-sdks` profile: every input pinned and checksummed, planned and refused before Docker starts.

Run from the component root: `python3 -m unittest tests.test_profile_claude_sdks -v`.

Held: the profile layers on the course's base set (composition of existing pins), its tag has the
profile form, nothing in it is waiting to be pinned, the SDK versions are the ones the course reads,
a changed checksum of each of the three kinds is refused by the entry's name before Docker starts, a
runtime outside the base set is refused by name, and the profile moves no base tag and no other
profile's tag.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "docker" / "profile"))
sys.path.insert(0, str(ROOT / "docker" / "profile_packages"))

import package_build  # noqa: E402
import package_kinds  # noqa: E402
import profile_build  # noqa: E402
import profile_plan  # noqa: E402
import test_profile as shared  # noqa: E402

NAME = "claude-sdks"
SET = ("python", "node", "java", "gradle", "kotlin")
AMD64, ARM64 = shared.AMD64, shared.ARM64
DIGEST = shared.IMAGE_DIGEST


class ThePlan(unittest.TestCase):
    def test_it_layers_on_the_course_base_set_and_names_both_images(self):
        profile = profile_plan.load(ROOT, NAME)
        self.assertEqual(profile["layers_on"], list(SET))
        self.assertEqual(profile["images"], ["runner", "editor"])
        self.assertEqual(len(profile["adds"]), 4)

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


class TheRealPins(unittest.TestCase):
    def test_nothing_is_waiting_and_every_check_passes(self):
        profile = profile_plan.load(ROOT, NAME)
        self.assertEqual(profile_plan.unpinned(profile), [])
        package_kinds.check(ROOT, NAME, profile, AMD64)
        profile_plan.check_projects(ROOT, NAME, profile)

    def test_the_kinds_are_carried_and_no_file_holds_a_placeholder(self):
        profile = profile_plan.load(ROOT, NAME)
        self.assertEqual([e["kind"] for e in profile["adds"]], ["python-wheels", "npm-packages", "project", "editor-extension"])
        for path in (ROOT / "profiles" / NAME).rglob("*"):
            if path.is_file():
                self.assertNotIn(profile_plan.PLACEHOLDER, path.read_text(encoding="utf-8", errors="replace"), path)
        self.assertNotIn(profile_plan.PLACEHOLDER, (ROOT / "profiles" / f"{NAME}.json").read_text(encoding="utf-8"))

    def test_the_pins_are_the_versions_the_course_reads(self):
        requirements = (ROOT / "profiles" / NAME / "requirements.txt").read_text(encoding="utf-8")
        for pin in ("anthropic==1.11.0", "mcp==2.2.0", "claude-agent-sdk==0.2.163", "pydantic==2.13.5"):
            self.assertIn(pin + " \\\n", requirements)
        manifest = json.loads((ROOT / "profiles" / NAME / "npm" / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["dependencies"], {"@anthropic-ai/claude-agent-sdk": "0.3.287", "@anthropic-ai/sdk": "0.131.0",
                                                    "@modelcontextprotocol/sdk": "1.31.0", "zod": "4.6.5"})
        self.assertEqual(manifest["devDependencies"], {"typescript": "5.9.3"})
        metadata = (ROOT / "profiles" / NAME / "jvm" / "gradle" / "verification-metadata.xml").read_text(encoding="utf-8")
        for coordinate in ('name="anthropic-java" version="2.68.0"', 'name="mcp" version="2.0.1"', 'name="kotlin-sdk" version="0.15.0"',
                           'name="junit-jupiter" version="5.10.2"', 'name="kotlin-test" version="2.4.20"'):
            self.assertIn(coordinate, metadata)

    def test_the_agent_sdk_binary_is_omitted_by_a_declared_step_in_each_language(self):
        profile = profile_plan.load(ROOT, NAME)
        wheel, packages = package_kinds.wheels(profile)[0], package_kinds.npm(profile)[0]
        self.assertEqual(wheel["remove_files"], ["claude_agent_sdk/_bundled/claude"])
        self.assertIs(packages["omit_optional"], True)
        self.assertIn("@modelcontextprotocol/sdk/client", packages["imports"])
        self.assertEqual(wheel["platforms"], ["linux/amd64"])

    def test_the_plan_names_the_project_and_starts_from_the_base_not_the_profile_recipe(self):
        built = package_kinds.plan(ROOT, NAME, "runner", [], AMD64)
        self.assertEqual(built.build_args["PROFILE_PROJECTS"], "jvm")
        self.assertEqual(built.build_args["PROFILE_HAS_PROJECTS"], "1")
        self.assertFalse(package_kinds.has_legacy_entries(profile_plan.load(ROOT, NAME)))


class TheRefusals(unittest.TestCase):
    def refused(self, plant, entry: str):
        import tempfile
        with tempfile.TemporaryDirectory(dir=ROOT / ".work" if (ROOT / ".work").is_dir() else None) as tmp:
            root = shared.context(tmp)
            plant(root)
            err = io.StringIO()
            with mock.patch.object(package_build.subprocess, "run", side_effect=AssertionError("Docker started")), \
                    contextlib.redirect_stderr(err):
                code = package_build.main(["--root", str(root), "--profile", NAME, "--image", "runner", "--base-digest", DIGEST])
            self.assertEqual(code, 2)
            self.assertIn(entry, err.getvalue())

    def test_a_changed_checksum_of_each_kind_is_refused_by_the_entry_name(self):
        def append(name):
            def plant(root):
                with (root / "profiles" / NAME / name).open("a", encoding="utf-8") as handle:
                    handle.write("\n")
            return plant
        self.refused(append("requirements.txt"), "python-sdks")
        self.refused(append("npm/package-lock.json"), "node-sdks")
        self.refused(append("jvm/gradle/verification-metadata.xml"), "jvm-sdks")

    def test_a_placeholder_pin_is_refused_by_the_entry_name(self):
        self.refused(lambda root: shared.edit_profile(root, NAME, lambda d: d["adds"][2].update(sha256=profile_plan.PLACEHOLDER)),
                     "jvm-sdks")

    def test_an_import_that_is_not_a_package_specifier_is_refused(self):
        self.refused(lambda root: shared.edit_profile(root, NAME, lambda d: d["adds"][1].update(imports=["x; rm -rf /"])),
                     "node-sdks")

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
