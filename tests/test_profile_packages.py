"""The profile entry kinds `python-wheels` and `npm-packages`: refusals, tags, recipe. No Docker.

Run from the component root: `python3 -m unittest tests.test_profile_packages -v`.

Held: each kind refuses, by entry and file name and before Docker starts, a pin that does not
match, a requirement with no hash or a range, a lockfile entry with no integrity, a missing file;
the kinds' bytes move the tag of the profile that names them and no other profile's or base's;
the profiles that existed before the kinds keep the tags recorded below (literals, taken from the
tree before this layer was added); the recipe installs with `--no-index` and with no network. The
image itself is proven by a build and `docs/measurements/package-profile-offline-proof.sh`.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "docker" / "profile"))
sys.path.insert(0, str(ROOT / "docker" / "profile_packages"))

import package_build as packages_build  # noqa: E402
import package_kinds  # noqa: E402
import profile_plan  # noqa: E402
import test_profile as shared  # noqa: E402

AMD64 = "linux/amd64"
NAME = "fixture-packages"
DIGEST = shared.IMAGE_DIGEST
#: Tags recorded BEFORE this layer existed, for amd64: (profile, image) -> tag.
RECORDED = {
    ("jvm-frameworks", "runner"): "code-server-toolchain/runner-jvm-frameworks:gradle-java-kotlin-amd64-e0de42be2689",
    ("jvm-frameworks", "editor"): "code-server-toolchain/editor-jvm-frameworks:gradle-java-kotlin-amd64-3d2ae58aa02d",
    ("fixture-libs", "runner"): "code-server-toolchain/runner-fixture-libs:gradle-java-kotlin-amd64-a4519ad7340e",
    ("fixture-libs", "editor"): "code-server-toolchain/editor-fixture-libs:gradle-java-kotlin-amd64-c1787d41c1b8",
    ("kotlin-editor", "editor"): "code-server-toolchain/editor-kotlin-editor:gradle-java-kotlin-amd64-db79c54d4663",
    ("claude-sdks", "runner"): "code-server-toolchain/runner-claude-sdks:gradle-java-kotlin-node-python-amd64-4069e92f83df",
    ("claude-sdks", "editor"): "code-server-toolchain/editor-claude-sdks:gradle-java-kotlin-node-python-amd64-467f25b40fba",
}


def context(tmp) -> Path:
    return shared.context(tmp)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repin(root: Path, requirements: str | None = None, lock: str | None = None) -> None:
    """Re-pin the fixture's entries to the files as they now are, so only the planted defect remains."""
    def change(data):
        for entry in data["adds"]:
            if entry["kind"] == "python-wheels" and requirements is not None:
                entry["sha256"] = sha(root / "profiles" / NAME / requirements)
            if entry["kind"] == "npm-packages" and lock is not None:
                entry["sha256"] = sha(root / "profiles" / NAME / lock / "package-lock.json")
    shared.edit_profile(root, NAME, change)


def check(root: Path, platform: str | None = AMD64) -> None:
    package_kinds.check(root, NAME, profile_plan.load(root, NAME), platform)


def run_main(root: Path) -> tuple[int, str]:
    err = io.StringIO()
    with mock.patch.object(packages_build.subprocess, "run", side_effect=AssertionError("Docker started")), \
            contextlib.redirect_stderr(err):
        code = packages_build.main(["--root", str(root), "--profile", NAME, "--image", "runner", "--base-digest", DIGEST])
    return code, err.getvalue()


class TheRealFixtureIsAccepted(unittest.TestCase):
    def test_every_check_passes_and_nothing_is_waiting(self):
        profile = profile_plan.load(ROOT, NAME)
        self.assertEqual(profile_plan.unpinned(profile), [])
        package_kinds.check(ROOT, NAME, profile, AMD64)

    def test_both_kinds_are_read_and_the_tag_has_the_profile_form(self):
        built = package_kinds.plan(ROOT, NAME, "runner", [], AMD64)
        self.assertRegex(built.tag, r"^code-server-toolchain/runner-fixture-packages:node-python-amd64-[0-9a-f]{12}$")
        self.assertEqual(built.build_args["PROFILE_HAS_NPM"], "1")
        self.assertIn("py-sdk|requirements.txt|claude_agent_sdk,mcp,pydantic|claude_agent_sdk/_bundled/claude|0", built.build_args["PROFILE_WHEELS"])
        self.assertEqual(built.build_args["PROFILE_NPM"], "node-sdk|npm|1")


class TheWheelRefusals(unittest.TestCase):
    def refused(self, plant, expect: str):
        with tempfile.TemporaryDirectory() as tmp:
            root = context(tmp)
            plant(root)
            with self.assertRaises(profile_plan.Refused) as caught:
                check(root)
            self.assertIn(expect, str(caught.exception))
            self.assertIn("py-sdk", str(caught.exception))
            code, err = run_main(root)
            self.assertEqual(code, 2)
            self.assertIn("py-sdk", err)

    def edit_requirements(self, root: Path, change) -> None:
        path = root / "profiles" / NAME / "requirements.txt"
        path.write_text(change(path.read_text(encoding="utf-8")), encoding="utf-8")

    def test_a_changed_hash_is_refused_by_the_file_that_no_longer_matches_its_pin(self):
        def plant(root):
            self.edit_requirements(root, lambda t: t.replace("--hash=sha256:f072", "--hash=sha256:0072", 1))
        self.refused(plant, "requirements.txt has sha256")

    def test_a_wheel_with_no_hash_is_refused_even_when_the_pin_was_updated(self):
        def plant(root):
            self.edit_requirements(root, lambda t: t + "extra-wheel==1.0\n")
            repin(root, requirements="requirements.txt")
        self.refused(plant, "'extra-wheel==1.0' has no `--hash=sha256")

    def test_a_range_a_url_and_an_option_are_refused(self):
        for line, expect in (("extra>=1.0 --hash=sha256:" + "a" * 64, "not an exact"),
                             ("extra @ https://example.invalid/x.whl", "not an exact"),
                             ("--index-url https://example.invalid/simple", "is an option")):
            with self.subTest(line=line):
                def plant(root, line=line):
                    self.edit_requirements(root, lambda t: t + line + "\n")
                    repin(root, requirements="requirements.txt")
                self.refused(plant, expect)

    def test_a_short_or_misspelt_hash_is_refused(self):
        def plant(root):
            self.edit_requirements(root, lambda t: t + "extra==1.0 --hash=sha256:abc\n")
            repin(root, requirements="requirements.txt")
        self.refused(plant, "has no `--hash")

    def test_a_missing_requirements_file_is_refused(self):
        self.refused(lambda root: (root / "profiles" / NAME / "requirements.txt").unlink(), "requirements.txt is missing")

    def test_a_path_that_climbs_out_of_the_profile_is_refused(self):
        self.refused(lambda root: shared.edit_profile(root, NAME, lambda d: d["adds"][0].update(requirements="../x.txt")),
                     "not a plain relative path")

    def test_a_platform_the_hashes_do_not_cover_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = context(tmp)
            with self.assertRaises(profile_plan.Refused) as caught:
                check(root, "linux/arm64")
            self.assertIn("py-sdk", str(caught.exception))
            self.assertIn("linux/arm64", str(caught.exception))

    def test_allow_sdist_must_be_a_reason_and_a_removal_must_stay_inside_site_packages(self):
        self.refused(lambda root: shared.edit_profile(root, NAME, lambda d: d["adds"][0].update(allow_sdist="")), "allow_sdist is a reason")
        self.refused(lambda root: shared.edit_profile(root, NAME, lambda d: d["adds"][0].update(remove_files=["../../bin/sh"])),
                     "remove_files")

    def test_a_still_unpinned_entry_is_refused_by_name_and_a_placeholder_requirements_too(self):
        self.refused(lambda root: shared.edit_profile(root, NAME, lambda d: d["adds"][0].update(requirements=profile_plan.PLACEHOLDER)),
                     profile_plan.PLACEHOLDER)


class TheNpmRefusals(unittest.TestCase):
    def refused(self, plant, expect: str):
        with tempfile.TemporaryDirectory() as tmp:
            root = context(tmp)
            plant(root)
            with self.assertRaises(profile_plan.Refused) as caught:
                check(root)
            self.assertIn(expect, str(caught.exception))
            self.assertIn("node-sdk", str(caught.exception))
            self.assertEqual(run_main(root)[0], 2)

    def lockfile(self, root: Path) -> Path:
        return root / "profiles" / NAME / "npm" / "package-lock.json"

    def test_an_edited_integrity_is_refused_by_the_lockfile_that_no_longer_matches_its_pin(self):
        def plant(root):
            path = self.lockfile(root)
            text = path.read_text(encoding="utf-8")
            marker = '"integrity": "sha512-'
            at = text.index(marker) + len(marker)
            path.write_text(text[:at] + ("A" if text[at] != "A" else "B") + text[at + 1:], encoding="utf-8")
        self.refused(plant, "package-lock.json has sha256")

    def test_an_entry_with_no_integrity_is_refused_even_when_the_pin_was_updated(self):
        def plant(root):
            path = self.lockfile(root)
            data = json.loads(path.read_text(encoding="utf-8"))
            victim = next(k for k, v in data["packages"].items() if k and "integrity" in v)
            del data["packages"][victim]["integrity"]
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            repin(root, lock="npm")
            plant.victim = victim
        self.refused(plant, "has no `integrity`")

    def test_a_missing_directory_or_lockfile_is_refused(self):
        self.refused(lambda root: self.lockfile(root).unlink(), "package-lock.json is missing")
        self.refused(lambda root: (root / "profiles" / NAME / "npm" / "package.json").unlink(), "package.json is missing")

        def plant(root):
            import shutil
            shutil.rmtree(root / "profiles" / NAME / "npm")
        self.refused(plant, "is not a directory")

    def test_omit_optional_defaults_to_false_and_must_be_a_boolean(self):
        built = None
        with tempfile.TemporaryDirectory() as tmp:
            root = context(tmp)
            shared.edit_profile(root, NAME, lambda d: d["adds"][1].pop("omit_optional"))
            built = package_kinds.plan(root, NAME, "runner", [], AMD64)
            self.assertEqual(built.build_args["PROFILE_NPM"], "node-sdk|npm|0")
        self.refused(lambda root: shared.edit_profile(root, NAME, lambda d: d["adds"][1].update(omit_optional="yes")), "omit_optional")


class NothingElseMoves(unittest.TestCase):
    def test_every_profile_that_existed_keeps_its_recorded_tag_through_both_planners(self):
        for (name, image), expected in RECORDED.items():
            with self.subTest(profile=name, image=image):
                self.assertEqual(profile_plan.plan(ROOT, name, image, [], AMD64).tag, expected)
                if not package_kinds.has_packages(profile_plan.load(ROOT, name)):
                    self.assertEqual(package_kinds.plan(ROOT, name, image, [], AMD64).tag, expected)

    def test_the_kinds_files_move_only_the_profile_that_names_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = context(tmp)
            before_bases = shared.base_tags(root)
            own = package_kinds.plan(root, NAME, "runner", [], AMD64).tag
            keys = [key for key in RECORDED if not package_kinds.has_packages(profile_plan.load(root, key[0]))]
            others = {key: package_kinds.plan(root, key[0], key[1], [], AMD64).tag for key in keys}
            path = root / "profiles" / NAME / "requirements.txt"
            path.write_text(path.read_text(encoding="utf-8") + "# a changed pin file\n", encoding="utf-8")
            self.assertNotEqual(package_kinds.plan(root, NAME, "runner", [], AMD64).tag, own)
            with (root / "docker" / "profile_packages" / "install.sh").open("a", encoding="utf-8") as handle:
                handle.write("# a changed recipe\n")
            self.assertEqual(shared.base_tags(root), before_bases)
            self.assertEqual({key: package_kinds.plan(root, key[0], key[1], [], AMD64).tag for key in keys}, others)
            self.assertEqual({key: profile_plan.plan(root, key[0], key[1], [], AMD64).tag for key in RECORDED}, RECORDED)

class TheRecipe(unittest.TestCase):
    def text(self, name: str) -> str:
        return (ROOT / "docker" / "profile_packages" / name).read_text(encoding="utf-8")

    def test_the_dockerfile_passes_the_components_own_static_rules(self):
        self.assertEqual(profile_plan.runner_plan.dockerfile_findings(self.text("Dockerfile")), [])

    def test_the_fetch_is_the_only_stage_with_a_network_and_the_install_has_none(self):
        docker = self.text("Dockerfile")
        self.assertIn("RUN --network=none \\\n    --mount=type=bind,from=profile-files", docker)
        self.assertEqual(docker.count("--network=none"), 2)
        fetch = self.text("fetch.sh")
        self.assertIn("--require-hashes", fetch)
        self.assertIn("--only-binary=:all:", fetch)
        self.assertIn("npm ci", fetch)

    def test_the_install_is_offline_hashed_and_proves_no_index_was_consulted(self):
        install = self.text("install.sh")
        self.assertIn("pip install --no-index --no-cache-dir --find-links", install)
        self.assertIn("--require-hashes", install)
        self.assertIn("Looking in indexes", install)
        self.assertIn('npm_config_cache="$P/npm-cache" npm ci --offline', install)

    def test_the_command_hands_the_files_and_recipe_as_named_contexts_and_the_image_as_a_start(self):
        built = package_kinds.plan(ROOT, NAME, "runner", [], AMD64)
        command = packages_build.docker_command(ROOT, built, "start:image", "scratch")
        self.assertIn("PROFILE_IMAGE=start:image", command)
        self.assertIn("--pull=false", command)
        self.assertEqual(command[command.index("-t") + 1], built.tag)
        self.assertTrue(any(c.startswith("profile-files=") for c in command))
        self.assertTrue(any(c.startswith("packages-recipe=") for c in command))
        self.assertTrue(any(c.startswith("warmers=") for c in command))

    def test_packages_and_projects_start_from_the_base_and_any_other_kind_from_the_profile_image(self):
        self.assertFalse(package_kinds.has_legacy_entries(profile_plan.load(ROOT, NAME)))
        self.assertFalse(package_kinds.has_legacy_entries(profile_plan.load(ROOT, "claude-sdks")))
        self.assertTrue(package_kinds.has_legacy_entries(profile_plan.load(ROOT, "jvm-frameworks")))

    def test_the_project_stage_runs_only_for_a_profile_that_has_a_project_entry(self):
        docker = self.text("Dockerfile")
        self.assertIn("FROM projects-${PROFILE_HAS_PROJECTS} AS ready", docker)
        self.assertEqual(docker.count("--network=none"), 2)
        self.assertEqual(package_kinds.plan(ROOT, NAME, "runner", [], AMD64).build_args["PROFILE_HAS_PROJECTS"], "0")
        self.assertEqual(package_kinds.plan(ROOT, "claude-sdks", "runner", [], AMD64).build_args["PROFILE_HAS_PROJECTS"], "1")
        command = packages_build.docker_command(ROOT, package_kinds.plan(ROOT, "claude-sdks", "runner", [], AMD64), "start:image")
        self.assertTrue(any(c.startswith("warmers=") for c in command))


if __name__ == "__main__":
    unittest.main()
