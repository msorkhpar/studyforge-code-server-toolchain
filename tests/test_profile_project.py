"""A profile's `project` entry kind: a Gradle multi-project and the checksum of its metadata. No Docker.

Run from the component root: `python3 -m unittest tests.test_profile_project -v`.

⭐ What is held. A `project` entry names a directory under `profiles/<name>/` and the sha256 of its
`gradle/verification-metadata.xml`. The directory's bytes (and the warmers that warm it) move the
profile's tag and no base tag; a wrong checksum, a missing file or a still-unpinned entry is
refused by name before Docker starts; `dependency` entries read exactly as before. The image
itself (warm, offline proof, read-only cache) is proven by a build, not here; this file holds
what the recipe must say so that build is the one the plan describes.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "docker" / "profile"))

import build_inputs  # noqa: E402
import profile_build  # noqa: E402
import profile_plan  # noqa: E402

AMD64 = "linux/amd64"
NAME = "fixture-libs"
FRAMEWORKS = "jvm-frameworks"
IMAGE_DIGEST = "sha256:" + "c" * 64
METADATA = "project/gradle/verification-metadata.xml"


def context(tmp) -> Path:
    root = build_inputs.copy_inputs(Path(tmp) / "context")
    shutil.copytree(ROOT / "profiles", root / "profiles")
    return root


def edit_profile(root: Path, name: str, change) -> None:
    path = root / "profiles" / f"{name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def tag(root: Path, name: str = NAME) -> str:
    return profile_plan.plan(root, name, "runner", [], AMD64).tag


def run_main(root: Path, name: str = NAME) -> tuple[int, str]:
    """`profile_build.main` for a real build line, with `subprocess.run` replaced so Docker can never start."""
    err = io.StringIO()
    with mock.patch.object(profile_build.subprocess, "run", side_effect=AssertionError("Docker started")), \
            contextlib.redirect_stderr(err):
        code = profile_build.main(["--profile", name, "--image", "runner", "--root", str(root),
                                   "--base-digest", IMAGE_DIGEST, "--platform", AMD64])
    return code, err.getvalue()


class TheProjectEntry(unittest.TestCase):
    def test_the_fixture_profile_is_pinned_and_checks(self):
        profile = profile_plan.load(ROOT, NAME)
        self.assertEqual([e["kind"] for e in profile["adds"]], ["project"])
        self.assertEqual(profile_plan.unpinned(profile), [])
        profile_plan.check_projects(ROOT, NAME, profile)

    def test_the_fixture_project_is_a_kotlin_module_with_junit_libraries_and_no_framework(self):
        text = (ROOT / "profiles" / NAME / "project" / "core" / "build.gradle.kts").read_text(encoding="utf-8")
        for needed in ('kotlin("jvm")', "junit-jupiter", "gson", "commons-lang3", "kotlinx-coroutines-core"):
            self.assertIn(needed, text)
        for framework in ("spring", "ktor", "micronaut", "quarkus"):
            self.assertNotIn(framework, text.lower())

    def test_the_plan_names_the_project_directory_for_the_recipe(self):
        built = profile_plan.plan(ROOT, NAME, "runner", [], AMD64)
        self.assertEqual(built.projects, ("project",))
        self.assertEqual(built.build_args["PROFILE_PROJECTS"], "project")
        self.assertTrue(built.build_args["PROFILE_ADDS"].startswith("libs|project:project|"))

    def test_a_dependency_profile_has_no_project_and_reads_as_before(self):
        built = profile_plan.plan(ROOT, FRAMEWORKS, "runner", [], AMD64)
        self.assertEqual(built.projects, ())
        self.assertEqual(built.build_args["PROFILE_PROJECTS"], "")
        self.assertIn("spring-boot|org.springframework.boot:spring-boot-starter:TO-BE-PINNED|TO-BE-PINNED",
                      built.build_args["PROFILE_ADDS"])

    def test_a_changed_project_file_moves_the_profile_tag_and_no_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = context(tmp)
            before, other = tag(root), tag(root, FRAMEWORKS)
            base = profile_plan.plan(root, NAME, "runner", [], AMD64).base_tag
            with (root / "profiles" / NAME / "project" / "core" / "build.gradle.kts").open("a", encoding="utf-8") as h:
                h.write("// a changed project file\n")
            self.assertNotEqual(tag(root), before)
            self.assertEqual(tag(root, FRAMEWORKS), other)
            self.assertEqual(profile_plan.plan(root, NAME, "runner", [], AMD64).base_tag, base)

    def test_a_changed_warmer_moves_a_project_profile_and_not_a_dependency_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = context(tmp)
            before, other = tag(root), tag(root, FRAMEWORKS)
            with (root / "prime" / "warm-gradle.sh").open("a", encoding="utf-8") as h:
                h.write("# a changed warmer\n")
            self.assertNotEqual(tag(root), before)
            self.assertEqual(tag(root, FRAMEWORKS), other)

    def test_the_docker_command_hands_the_project_and_the_warmers_as_named_contexts(self):
        built = profile_plan.plan(ROOT, NAME, "runner", [], AMD64)
        command = profile_build.docker_command(ROOT, built, IMAGE_DIGEST)
        self.assertIn(f"profile-projects={ROOT / 'profiles' / NAME}", command)
        self.assertIn(f"warmers={ROOT / 'prime'}", command)
        self.assertIn("PROFILE_PROJECTS=project", command)


class TheRefusals(unittest.TestCase):
    def test_a_wrong_checksum_file_is_refused_by_name_before_docker_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = context(tmp)
            path = root / "profiles" / NAME / METADATA
            data = path.read_bytes()
            self.assertIn(b"sha256 value=", data)
            path.write_bytes(data.replace(b"sha256 value=", b"sha256 value=0", 1))
            self.assertNotEqual(path.read_bytes(), data)
            code, err = run_main(root)
            self.assertEqual(code, 2)
            for named in ("libs", "verification-metadata.xml", "fixture-libs"):
                self.assertIn(named, err)

    def test_the_real_tree_reaches_the_docker_command(self):
        with mock.patch.object(profile_build.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            self.assertEqual(profile_build.main(["--profile", NAME, "--image", "runner", "--platform", AMD64,
                                                 "--base-digest", IMAGE_DIGEST]), 0)
        self.assertEqual(run.call_count, 1)

    def test_an_entry_still_reading_to_be_pinned_refuses_a_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = context(tmp)
            edit_profile(root, NAME, lambda d: d["adds"][0].update(sha256=profile_plan.PLACEHOLDER))
            self.assertEqual(profile_plan.unpinned(profile_plan.load(root, NAME)), ["libs"])
            code, err = run_main(root)
            self.assertEqual(code, 2)
            self.assertIn("TO-BE-PINNED", err)
            self.assertIn("libs", err)

    def test_a_path_still_reading_to_be_pinned_is_unpinned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = context(tmp)
            edit_profile(root, NAME, lambda d: d["adds"][0].update(path=profile_plan.PLACEHOLDER))
            self.assertEqual(profile_plan.unpinned(profile_plan.load(root, NAME)), ["libs"])

    def test_a_missing_directory_or_checksum_file_is_refused_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = context(tmp)
            (root / "profiles" / NAME / METADATA).unlink()
            code, err = run_main(root)
            self.assertEqual(code, 2)
            self.assertIn("verification-metadata.xml is missing", err)
            shutil.rmtree(root / "profiles" / NAME / "project")
            code, err = run_main(root)
        self.assertEqual(code, 2)
        self.assertIn("is not a directory", err)

    def test_a_path_outside_the_profile_directory_is_refused(self):
        for bad in ("../x", "/etc", "a/../../x", ""):
            with self.subTest(path=bad), tempfile.TemporaryDirectory() as tmp:
                root = context(tmp)
                edit_profile(root, NAME, lambda d: d["adds"][0].update(path=bad))
                with self.assertRaises(profile_plan.Refused):
                    profile_plan.plan(root, NAME, "runner", [], AMD64)


class TheRecipe(unittest.TestCase):
    TEXT = (ROOT / profile_plan.DOCKERFILE).read_text(encoding="utf-8")

    def test_the_recipe_passes_the_components_own_static_rules(self):
        self.assertEqual(profile_plan.runner_plan.dockerfile_findings(self.TEXT), [])

    def test_the_recipe_warms_with_the_course_warmers_and_proves_offline(self):
        self.assertIn("warm-gradle.sh warm", self.TEXT)
        self.assertIn("warm-gradle.sh prove", self.TEXT)
        self.assertIn("RUN --network=none", self.TEXT)

    def test_the_recipe_exposes_a_read_only_cache_and_no_user_home(self):
        self.assertIn("ENV GRADLE_RO_DEP_CACHE=/opt/profile/gradle-ro-cache", self.TEXT)
        self.assertIn("a-w /opt/profile", self.TEXT)
        self.assertNotIn("ENV GRADLE_USER_HOME", self.TEXT)


if __name__ == "__main__":
    unittest.main()
