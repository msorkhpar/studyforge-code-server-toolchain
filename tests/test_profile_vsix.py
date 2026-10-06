"""An `editor-extension` entry with `install: vsix`: planned, refused and fetched. No Docker.

Run from the component root: `python3 -m unittest tests.test_profile_vsix -v`.

Held: the `claude-sdks` editor image is told to install one pinned extension archive (a Python language
server) and the runner image none; an entry this recipe cannot honour is refused by its name before Docker
starts; an archive whose digest is not the pinned one is refused by the fetch step naming the entry and
stores nothing; a profile that carries such an entry never runs the profile recipe's patch step; an
`editor-extension` without `install` is read as it always was. The installed extension is proved offline
in a real editor by `docs/measurements/editor-diagnostics-offline.py`.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "docker" / "profile"))
sys.path.insert(0, str(ROOT / "docker" / "profile_packages"))

import package_build  # noqa: E402
import package_kinds  # noqa: E402
import profile_plan  # noqa: E402
import test_profile as shared  # noqa: E402

NAME = "claude-sdks"
AMD64 = shared.AMD64
DIGEST = shared.IMAGE_DIGEST
PROVIDES = "detachhead.basedpyright@1.40.1"


def entry_of(profile: dict) -> dict:
    return package_kinds.vsix(profile)[0]


class ThePlan(unittest.TestCase):
    def test_the_editor_installs_the_one_archive_and_the_runner_none(self):
        editor = package_kinds.plan(ROOT, NAME, "editor", [], AMD64).build_args
        runner = package_kinds.plan(ROOT, NAME, "runner", [], AMD64).build_args
        self.assertEqual(len(editor["PROFILE_VSIX"].splitlines()), 1)
        self.assertTrue(editor["PROFILE_VSIX"].endswith("|" + PROVIDES))
        self.assertIn("basedpyright.analysis.typeCheckingMode", editor["PROFILE_VSIX_SEED"])
        self.assertEqual(runner["PROFILE_VSIX"], "")
        self.assertEqual(runner["PROFILE_VSIX_SEED"], "")

    def test_the_profile_never_runs_the_profile_recipes_patch_step(self):
        profile = profile_plan.load(ROOT, NAME)
        self.assertFalse(package_kinds.has_legacy_entries(profile))
        self.assertTrue(package_kinds.has_legacy_entries(profile_plan.load(ROOT, "kotlin-editor")))

    def test_an_archive_alone_still_makes_a_package_layer(self):
        only = {"adds": [dict(entry_of(profile_plan.load(ROOT, NAME)))]}
        self.assertTrue(package_kinds.has_packages(only))
        self.assertFalse(package_kinds.has_legacy_entries(only))

    def test_an_extension_without_install_is_read_as_before(self):
        kotlin = profile_plan.load(ROOT, "kotlin-editor")
        self.assertEqual(package_kinds.vsix(kotlin), [])
        self.assertFalse(package_kinds.has_packages(kotlin))
        package_kinds.check_vsix("kotlin-editor", kotlin)


class TheRefusals(unittest.TestCase):
    def refused(self, plant, words: str):
        with tempfile.TemporaryDirectory(dir=ROOT / ".work" if (ROOT / ".work").is_dir() else None) as tmp:
            root = shared.context(tmp)
            shared.edit_profile(root, NAME, lambda data: plant(data["adds"][3]))
            err = io.StringIO()
            with mock.patch.object(package_build.subprocess, "run", side_effect=AssertionError("Docker started")), \
                    contextlib.redirect_stderr(err):
                code = package_build.main(["--root", str(root), "--profile", NAME, "--image", "editor", "--base-digest", DIGEST])
            self.assertEqual(code, 2)
            self.assertIn("basedpyright", err.getvalue())
            self.assertIn(words, err.getvalue())

    def test_each_entry_this_recipe_cannot_honour_is_refused_by_name(self):
        self.refused(lambda e: e.update(install="zip"), "install 'zip'")
        self.refused(lambda e: e.update(url="https://example.invalid/x.zip"), "versioned .vsix")
        self.refused(lambda e: e.update(url="http://example.invalid/x.vsix"), "https address of a versioned")
        self.refused(lambda e: e.update(sha256="abc"), "still read")
        self.refused(lambda e: e.update(provides="basedpyright"), "publisher.name@version")
        self.refused(lambda e: e.update(images=["runner", "editor"]), "editor image only")
        self.refused(lambda e: e.update(strip=1), "patches and strip")

    def test_a_placeholder_pin_is_refused_by_name(self):
        self.refused(lambda e: e.update(sha256=profile_plan.PLACEHOLDER), "TO-BE-PINNED")


class TheFetch(unittest.TestCase):
    def run_fetch(self, source: Path, destination: Path, pinned: str):
        script = ROOT / "docker" / "profile_packages" / "fetch_vsix.py"
        return subprocess.run([sys.executable, str(script), source.as_uri(), str(destination), pinned],
                              capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def test_the_pinned_archive_is_stored_and_another_is_refused_naming_both_digests(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".work" if (ROOT / ".work").is_dir() else None) as tmp:
            source = Path(tmp) / "x.vsix"
            source.write_bytes(b"an archive")
            good = hashlib.sha256(b"an archive").hexdigest()
            stored = Path(tmp) / "out" / "x.vsix"
            done = self.run_fetch(source, stored, good)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(stored.read_bytes(), b"an archive")
            wrong = Path(tmp) / "out" / "y.vsix"
            done = self.run_fetch(source, wrong, "0" * 64)
            self.assertEqual(done.returncode, 1)
            self.assertIn(good, done.stderr)
            self.assertIn("0" * 64, done.stderr)
            self.assertFalse(wrong.exists())


class TheRecipe(unittest.TestCase):
    def text(self, name: str) -> str:
        return (ROOT / "docker" / "profile_packages" / name).read_text(encoding="utf-8")

    def test_the_archive_is_fetched_with_the_network_and_installed_without_it(self):
        self.assertIn("fetch_vsix.py", self.text("fetch.sh"))
        install = self.text("install.sh")
        self.assertIn("--install-extension", install)
        self.assertIn("--list-extensions --show-versions", install)
        docker = self.text("Dockerfile")
        self.assertEqual(docker.count("--network=none"), 2)
        self.assertIn("RUN --network=none \\\n    --mount=type=bind,from=profile-files", docker)
        self.assertNotIn("curl", install)
        self.assertEqual(profile_plan.runner_plan.dockerfile_findings(docker), [])

    def test_the_archive_is_pinned_by_digest_and_by_its_published_name(self):
        entry = entry_of(profile_plan.load(ROOT, NAME))
        self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(entry["url"].endswith("/" + entry["provides"].replace("@", "-") + ".vsix"))


if __name__ == "__main__":
    unittest.main()
