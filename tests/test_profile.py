"""A profile image's plan and tag: pure, no Docker.

Run from the component root: `python3 -m unittest tests.test_profile -v`.

⭐ What is held. A new pinned input (the framework profile's dependencies now, a runtime later)
enters a profile image and no base: the shared bases' tags stay byte-identical, and the
profile's own tag is a digest of its own inputs and the base's tag. Every rule is asserted both
ways: the real tree passes, and a planted violation is caught (the plants are run by hand and
named in the change that adds this file).
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "docker" / "profile"))

import build_inputs  # noqa: E402
import profile_build  # noqa: E402
import profile_plan  # noqa: E402
import test_compatibility_baseline as baseline  # noqa: E402

AMD64, ARM64 = "linux/amd64", "linux/arm64"
NAME = "jvm-frameworks"
SET = ("gradle", "java", "kotlin")
SHA = "b" * 64
IMAGE_DIGEST = "sha256:" + "c" * 64


def context(tmp) -> Path:
    """A copy of every build input, plus the profile files and recipe a profile reads."""
    root = build_inputs.copy_inputs(Path(tmp) / "context")
    shutil.copytree(ROOT / "profiles", root / "profiles")
    return root


def base_tags(root: Path) -> dict:
    """The tag of every recorded set, both images, both architectures, from the plans themselves."""
    found = {}
    for image in ("runner", "editor"):
        for runtimes in baseline.SETS:
            for platform in (AMD64, ARM64):
                names = [n for n in runtimes.split(",") if n]
                found[(image, runtimes, platform)] = profile_plan.base_plan(root, image, names, platform).tag
    return found


def edit_profile(root: Path, name: str, change) -> None:
    path = root / "profiles" / f"{name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


class TheBasesStayWhereTheyWere(unittest.TestCase):
    def test_a_profile_is_in_no_base_input(self):
        for entry in (profile_plan.PROFILES_DIR, profile_plan.RECIPE):
            with self.subTest(entry=entry):
                self.assertNotIn(entry, profile_plan.runner_plan.INPUT_ROOTS)
                self.assertNotIn(entry, profile_plan.editor_plan.OWN_INPUTS)

    def test_the_bases_tags_are_the_recorded_ones(self):
        for (image, runtimes, platform), tag in base_tags(ROOT).items():
            with self.subTest(image=image, runtimes=runtimes, platform=platform):
                arch = baseline.ARCH[platform]
                name = baseline.SETS[runtimes]
                self.assertEqual(tag, f"{baseline.REPOSITORY[image]}:{name}-{arch}-{baseline.DIGEST[image]}")

    def test_editing_a_profile_entry_moves_no_base_tag_and_only_that_profiles_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = context(tmp)
            before = base_tags(root)
            runner0 = profile_plan.plan(root, NAME, "runner", [], AMD64).tag
            editor0 = profile_plan.plan(root, NAME, "editor", [], AMD64).tag
            edit_profile(root, NAME, lambda d: d["adds"][0].update(coordinates="org.example:changed:1.0"))
            self.assertEqual(base_tags(root), before)
            self.assertNotEqual(profile_plan.plan(root, NAME, "runner", [], AMD64).tag, runner0)
            self.assertNotEqual(profile_plan.plan(root, NAME, "editor", [], AMD64).tag, editor0)

    def test_adding_an_entry_to_a_profile_moves_no_base_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = context(tmp)
            before = base_tags(root)
            runner0 = profile_plan.plan(root, NAME, "runner", [], AMD64).tag
            edit_profile(root, NAME, lambda d: d["adds"].append(
                {"kind": "dependency", "id": "extra", "coordinates": "org.example:extra:1", "sha256": SHA}))
            self.assertEqual(base_tags(root), before)
            self.assertNotEqual(profile_plan.plan(root, NAME, "runner", [], AMD64).tag, runner0)

    def test_a_hypothetical_new_runtime_pinned_as_a_profile_moves_no_recorded_tag(self):
        """A later runtime is added as its own profile file: no base tag and no other profile's tag moves."""
        with tempfile.TemporaryDirectory() as tmp:
            root = context(tmp)
            before = base_tags(root)
            runner0 = profile_plan.plan(root, NAME, "runner", [], AMD64).tag
            editor0 = profile_plan.plan(root, NAME, "editor", [], AMD64).tag
            (root / "profiles" / "newlang.json").write_text(json.dumps({
                "profiles_api": 1, "name": "newlang", "about": "a hypothetical runtime",
                "layers_on": ["java"], "images": ["runner", "editor"],
                "adds": [{"kind": "runtime", "id": "newlang", "coordinates": "https://example.invalid/newlang.tgz",
                          "sha256": SHA}]}), encoding="utf-8")
            self.assertEqual(base_tags(root), before)
            self.assertEqual(profile_plan.plan(root, NAME, "runner", [], AMD64).tag, runner0)
            self.assertEqual(profile_plan.plan(root, NAME, "editor", [], AMD64).tag, editor0)
            own = profile_plan.plan(root, "newlang", "runner", ["java"], AMD64).tag
            self.assertTrue(own.startswith("code-server-toolchain/runner-newlang:java-amd64-"))
            self.assertNotEqual(own, runner0)

    def test_the_profile_files_are_read_by_the_plans_only_through_the_profile(self):
        """Even the recipe directory moves no base tag: only the profile's own."""
        with tempfile.TemporaryDirectory() as tmp:
            root = context(tmp)
            before = base_tags(root)
            runner0 = profile_plan.plan(root, NAME, "runner", [], AMD64).tag
            with (root / "docker" / "profile" / "Dockerfile").open("a", encoding="utf-8") as handle:
                handle.write("# a changed recipe\n")
            self.assertEqual(base_tags(root), before)
            self.assertNotEqual(profile_plan.plan(root, NAME, "runner", [], AMD64).tag, runner0)


class TheProfileTag(unittest.TestCase):
    def test_the_tag_names_the_profile_the_set_and_the_architecture(self):
        runner = profile_plan.plan(ROOT, NAME, "runner", [], AMD64)
        editor = profile_plan.plan(ROOT, NAME, "editor", [], ARM64)
        self.assertRegex(runner.tag, r"^code-server-toolchain/runner-jvm-frameworks:gradle-java-kotlin-amd64-[0-9a-f]{12}$")
        self.assertRegex(editor.tag, r"^code-server-toolchain/editor-jvm-frameworks:gradle-java-kotlin-arm64-[0-9a-f]{12}$")
        self.assertEqual(runner.published, "studyforge-code-toolchain-runner-jvm-frameworks")
        self.assertEqual(editor.published, "studyforge-code-toolchain-editor-jvm-frameworks")

    def test_the_base_is_the_shared_bases_own_tag(self):
        runner = profile_plan.plan(ROOT, NAME, "runner", [], AMD64)
        self.assertEqual(runner.base_tag, "code-server-toolchain/runner:gradle-java-kotlin-amd64-" + baseline.DIGEST["runner"])
        self.assertEqual(runner.build_args["BASE_IMAGE"], runner.base_tag)

    def test_a_change_to_the_base_moves_the_profile_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = context(tmp)
            runner0 = profile_plan.plan(root, NAME, "runner", [], AMD64)
            editor0 = profile_plan.plan(root, NAME, "editor", [], AMD64)
            with (root / "docker" / "minimal" / "Dockerfile").open("a", encoding="utf-8") as handle:
                handle.write("# a changed shared input\n")
            runner1 = profile_plan.plan(root, NAME, "runner", [], AMD64)
            editor1 = profile_plan.plan(root, NAME, "editor", [], AMD64)
            self.assertNotEqual(runner1.base_tag, runner0.base_tag)
            self.assertNotEqual(runner1.tag, runner0.tag)
            # the editor carries the runner's digest, so its base and profile move as well
            self.assertNotEqual(editor1.tag, editor0.tag)

    def test_an_editor_only_change_moves_the_editor_profile_and_not_the_runner_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = context(tmp)
            runner0 = profile_plan.plan(root, NAME, "runner", [], AMD64).tag
            editor0 = profile_plan.plan(root, NAME, "editor", [], AMD64).tag
            with (root / "docker" / "editor" / "Dockerfile").open("a", encoding="utf-8") as handle:
                handle.write("# a changed editor input\n")
            self.assertEqual(profile_plan.plan(root, NAME, "runner", [], AMD64).tag, runner0)
            self.assertNotEqual(profile_plan.plan(root, NAME, "editor", [], AMD64).tag, editor0)

    def test_a_wider_base_set_gives_another_tag(self):
        narrow = profile_plan.plan(ROOT, NAME, "runner", [], AMD64).tag
        wide = profile_plan.plan(ROOT, NAME, "runner", ["gradle", "java", "kotlin", "node"], AMD64).tag
        self.assertNotEqual(narrow, wide)
        self.assertIn(":gradle-java-kotlin-node-amd64-", wide)

    def test_the_command_line_prints_the_plans_tag(self):
        for image in ("runner", "editor"):
            done = subprocess.run([sys.executable, str(ROOT / "docker" / "profile" / "profile_build.py"),
                                   "--profile", NAME, "--image", image, "--platform", AMD64, "--print-tag"],
                                  capture_output=True, text=True, stdin=subprocess.DEVNULL, check=False)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout.strip(), profile_plan.plan(ROOT, NAME, image, [], AMD64).tag)


class TheRefusals(unittest.TestCase):
    def test_the_stub_entries_are_unpinned_and_a_build_is_refused(self):
        profile = profile_plan.load(ROOT, NAME)
        self.assertEqual(profile_plan.unpinned(profile), [e["id"] for e in profile["adds"]])
        built = profile_plan.plan(ROOT, NAME, "runner", [], AMD64)
        self.assertEqual(profile_build.main(["--profile", NAME, "--image", "runner",
                                             "--base-digest", IMAGE_DIGEST]), 2)
        self.assertTrue(built.tag)

    def test_a_pinned_profile_reports_nothing_waiting(self):
        profile = copy.deepcopy(profile_plan.load(ROOT, NAME))
        for entry in profile["adds"]:
            entry.update(coordinates="org.example:pinned:1.0", sha256=SHA)
        self.assertEqual(profile_plan.unpinned(profile), [])

    def test_a_build_starts_from_the_base_by_tag_and_digest(self):
        built = profile_plan.plan(ROOT, NAME, "runner", [], AMD64)
        self.assertEqual(profile_plan.base_reference(built, IMAGE_DIGEST), f"{built.base_tag}@{IMAGE_DIGEST}")
        for bad in (None, "", "latest", "sha256:abc", "c" * 64):
            with self.subTest(digest=bad), self.assertRaises(profile_plan.Refused):
                profile_plan.base_reference(built, bad)

    def test_a_set_missing_what_the_profile_layers_on_is_refused(self):
        with self.assertRaises(profile_plan.Refused) as caught:
            profile_plan.plan(ROOT, NAME, "runner", ["java"], AMD64)
        self.assertIn("gradle", str(caught.exception))

    def test_an_unknown_profile_or_image_is_refused(self):
        for args in (("nosuch", "runner"), ("../x", "runner"), (NAME, "toolbox")):
            with self.subTest(args=args), self.assertRaises(profile_plan.Refused):
                profile_plan.plan(ROOT, args[0], args[1], [], AMD64)

    def test_the_docker_command_names_the_base_by_digest_and_pulls_nothing(self):
        built = profile_plan.plan(ROOT, NAME, "runner", [], AMD64)
        command = profile_build.docker_command(ROOT, built, IMAGE_DIGEST)
        self.assertIn(f"BASE_IMAGE={built.base_tag}@{IMAGE_DIGEST}", command)
        self.assertIn("--pull=false", command)
        self.assertEqual(command[command.index("-t") + 1], built.tag)


class TheRecipe(unittest.TestCase):
    def test_the_dockerfile_passes_the_components_own_static_rules(self):
        text = (ROOT / profile_plan.DOCKERFILE).read_text(encoding="utf-8")
        self.assertEqual(profile_plan.runner_plan.dockerfile_findings(text), [])
        self.assertIn("FROM ${BASE_IMAGE}", text)

    def test_every_profile_file_has_the_shape_the_plan_reads(self):
        for path in sorted((ROOT / "profiles").glob("*.json")):
            with self.subTest(profile=path.stem):
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data["name"], path.stem)
                self.assertEqual(data["profiles_api"], 1)
                self.assertTrue(set(data["images"]) <= set(profile_plan.IMAGES))
                ids = [e["id"] for e in data["adds"]]
                self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
