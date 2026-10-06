"""A profile's `editor-extension` entry kind: an archive and the settings that point at it. No Docker.

Run from the component root: `python3 -m unittest tests.test_profile_extension -v`.

⭐ What is held. An `editor-extension` entry names a pinned archive, the images it belongs to and the
settings that make the editor use it. It reaches only the images it names; its settings become one
Kotlin block of the editor's settings seed; a wrong archive is refused by name; and the editor's
own recipe, `editor-pins.json` and every base tag stay as they were, because the extension is a
profile input and not an editor input. The image itself (installed, seeded, working with the
network cut off) is proven by a build and a browser session, not here.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import shutil
import stat
import subprocess
import tarfile
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "docker" / "profile"))

import build_inputs  # noqa: E402
import fetch_extension  # noqa: E402
import profile_build  # noqa: E402
import profile_plan  # noqa: E402
import test_compatibility_baseline as baseline  # noqa: E402
import test_editor_plan  # noqa: E402
import test_profile  # noqa: E402

AMD64 = "linux/amd64"
NAME = "kotlin-editor"
ID = "kotlin-language-server"
JDK = "kotlin-jdk"
PATCHED = "/opt/code-server/extensions/fwcd.kotlin-0.2.36/dist/extension.js"
IMAGE_DIGEST = "sha256:" + "c" * 64
BAKED = "/opt/code-server/kotlin-ls/bin/kotlin-language-server"
SERVER = "/opt/profile/editor-extensions/kotlin-language-server/server/bin/kotlin-language-server"


def context(tmp) -> Path:
    root = build_inputs.copy_inputs(Path(tmp) / "context")
    shutil.copytree(ROOT / "profiles", root / "profiles")
    return root


def plan(root: Path, image: str = "editor"):
    return profile_plan.plan(root, NAME, image, [], AMD64)


def run_main(root: Path, image: str = "editor") -> tuple[int, str]:
    err = io.StringIO()
    with mock.patch.object(profile_build.subprocess, "run", side_effect=AssertionError("Docker started")), \
            contextlib.redirect_stderr(err):
        code = profile_build.main(["--profile", NAME, "--image", image, "--root", str(root),
                                   "--base-digest", IMAGE_DIGEST, "--platform", AMD64])
    return code, err.getvalue()


def archive(path: Path) -> str:
    """A small zip with one executable member, as the server's own archive has; returns its sha256."""
    info = zipfile.ZipInfo("server/bin/run")
    info.external_attr = (stat.S_IFREG | 0o755) << 16
    with zipfile.ZipFile(path, "w") as zipped:
        zipped.writestr(info, "#!/bin/sh\n")
        zipped.writestr("server/lib/a.jar", "jar")
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TheEntry(unittest.TestCase):
    def test_the_profile_is_pinned_exactly_and_names_only_the_editor(self):
        profile = profile_plan.load(ROOT, NAME)
        self.assertEqual(profile_plan.unpinned(profile), [])
        server, jdk = profile["adds"]
        for entry in profile["adds"]:
            self.assertEqual((entry["kind"], entry["images"]), ("editor-extension", ["editor"]))
            self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$")
        entry = server
        self.assertEqual((server["id"], jdk["id"]), (ID, JDK))
        self.assertEqual((jdk["platform"], jdk["strip"]), ("linux/amd64", 1))
        self.assertRegex(jdk["url"], r"^https://github\.com/adoptium/temurin21-binaries/releases/download/[^ ]+\.tar\.gz$")
        self.assertEqual(profile["images"], ["editor"])
        self.assertRegex(entry["url"], r"^https://github\.com/fwcd/kotlin-language-server/releases/download/\d+\.\d+\.\d+/server\.zip$")
        self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$")

    def test_the_editor_plan_fetches_the_archive_and_the_runner_plan_fetches_nothing(self):
        editor = plan(ROOT)
        self.assertEqual(editor.build_args["PROFILE_EXTENSIONS"].split("|")[0], ID)
        self.assertEqual([line.split("|")[0] for line in editor.build_args["PROFILE_EXTENSIONS"].splitlines()], [ID, JDK])
        for entry in profile_plan.load(ROOT, NAME)["adds"]:
            self.assertIn(entry["sha256"], editor.build_args["PROFILE_EXTENSIONS"])
        self.assertTrue(editor.build_args["PROFILE_EXTENSIONS"].splitlines()[1].endswith("|1"))
        with self.assertRaises(profile_plan.Refused):
            plan(ROOT, "runner")  # the profile is not built for the runner at all

    def test_an_entry_naming_only_the_runner_reaches_no_editor_and_its_settings_are_not_seeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = context(tmp)
            test_profile.edit_profile(root, NAME, lambda d: (d.update(images=["runner", "editor"]),
                                                             [e.update(images=["runner"]) for e in d["adds"]]))
            self.assertEqual(plan(root, "editor").build_args["PROFILE_EXTENSIONS"], "")
            self.assertEqual(plan(root, "editor").build_args["PROFILE_SEED"], "")
            self.assertEqual(plan(root, "editor").build_args["PROFILE_PATCHES"], "")
            self.assertIn(ID, plan(root, "runner").build_args["PROFILE_EXTENSIONS"])
            self.assertEqual(plan(root, "runner").build_args["PROFILE_SEED"].count("@runtime kotlin"), 1)

    def test_a_profile_without_the_kind_reads_exactly_as_before(self):
        for name in ("jvm-frameworks", "fixture-libs"):
            with self.subTest(profile=name):
                args = profile_plan.plan(ROOT, name, "runner", [], AMD64).build_args
                self.assertEqual((args["PROFILE_EXTENSIONS"], args["PROFILE_SEED"], args["PROFILE_PATCHES"]), ("", "", ""))


class TheSeedBlock(unittest.TestCase):
    def seed_after_the_recipe(self, root: Path) -> str:
        """The editor's real settings seed with the block spliced in the way the recipe does (after the line `{`)."""
        text = (root / "docker" / "editor" / "seed" / "settings.json").read_text(encoding="utf-8")
        block = plan(root).build_args["PROFILE_SEED"]
        return re.sub(r"^\{$", lambda _: "{\n" + block, text, count=1, flags=re.M)

    def test_the_block_holds_the_settings_the_extension_needs_to_stay_offline(self):
        block = plan(ROOT).build_args["PROFILE_SEED"]
        self.assertTrue(block.lstrip().startswith("// @runtime kotlin"))
        self.assertTrue(block.rstrip().endswith("// @end kotlin"))
        self.assertIn(f'"kotlin.languageServer.path": "{SERVER}"', block)
        self.assertIn('"kotlin.java.home": "/opt/profile/editor-extensions/kotlin-jdk"', block)
        self.assertIn('"kotlin.debugAdapter.enabled": false', block)

    def test_the_seed_is_still_valid_settings_with_and_without_the_other_blocks(self):
        text = self.seed_after_the_recipe(ROOT)
        for dropped in ((), ("java",), ("java", "python")):
            with self.subTest(dropped=dropped):
                kept = text
                for runtime in dropped:
                    kept = re.sub(rf"// @runtime {runtime}$.*?// @end {runtime}$", "", kept, flags=re.M | re.S)
                parsed = json.loads("\n".join(l for l in kept.splitlines() if not l.strip().startswith("//")))
                self.assertEqual(parsed["kotlin.languageServer.path"], SERVER)

    def test_the_editors_own_seed_names_the_baked_server_and_no_profile_seed_points_elsewhere(self):
        """The server is baked into the editor: its Machine settings seed names exactly that path, the recipe
        seeds `kls-classpath` and the entrypoint writes it on every start; a profile seed may not move the path."""
        editor = ROOT / "docker" / "editor"
        epins = json.loads((ROOT / "editor-pins.json").read_text(encoding="utf-8"))
        self.assertEqual(epins["kotlin_language_server"]["dir"] + "/bin/kotlin-language-server", BAKED)
        machine = json.loads(test_editor_plan.planned().build_args["KOTLIN_LS_SETTINGS"])
        self.assertEqual(machine["kotlin.languageServer.path"], BAKED)
        self.assertTrue((editor / "kls-classpath").is_file())
        self.assertIn("install -m 755 /tmp/kls-classpath /opt/code-server/seed/kls-classpath",
                      (editor / "Dockerfile").read_text(encoding="utf-8"))
        self.assertIn("SEED_KLS=/opt/code-server/seed/kls-classpath", (editor / "entrypoint.sh").read_text(encoding="utf-8"))
        for path in editor.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                with self.subTest(file=path.name):
                    text = path.read_text(encoding="utf-8", errors="ignore")
                    for value in re.findall(r'"kotlin\.languageServer\.path"\s*:\s*"([^"]*)"', text):
                        self.assertEqual(value, BAKED)
        for path in (editor / "seed").glob("*.json"):
            with self.subTest(seed=path.name):  # the reader's own seeds stay clean: the path is a Machine setting
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("languageServer.path", text)
                self.assertNotIn("kotlin-language-server", text)
        self.assertNotIn("kotlin-language-server", (ROOT / "pins.json").read_text(encoding="utf-8"))
        for path in sorted((ROOT / "profiles").glob("*.json")):
            profile = profile_plan.load(ROOT, path.stem)
            if "editor" not in profile.get("images", []):
                continue
            with self.subTest(profile=path.stem):
                block = profile_plan.plan(ROOT, path.stem, "editor", [], AMD64).build_args["PROFILE_SEED"]
                for value in re.findall(r'"kotlin\.languageServer\.path"\s*:\s*"([^"]*)"', block):
                    self.assertEqual(value, BAKED)


class ThePatches(unittest.TestCase):
    def test_the_plan_hands_the_patch_to_the_editor_as_one_line(self):
        (line,) = plan(ROOT).build_args["PROFILE_PATCHES"].splitlines()
        file, before, after, *texts = line.split("|")
        self.assertEqual(file, PATCHED)
        self.assertRegex(before, r"^[0-9a-f]{64}$")
        self.assertRegex(after, r"^[0-9a-f]{64}$")
        self.assertNotEqual(before, after)
        self.assertEqual(texts, ["typeof navigator", "typeof void 0", "if(!g.getConfig().initialized){", "if(!1){"])

    def test_a_patch_that_is_not_well_formed_is_refused_by_name(self):
        bad = {"a file outside the extensions": {"file": "/etc/passwd"},
               "a checksum that is not one": {"sha256": "TO-BE-PINNED"},
               "no replacement": {"replace": []},
               "a text with the line separator": {"replace": [["a|b", "c"]]}}
        for label, change in bad.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                root = context(tmp)
                test_profile.edit_profile(root, NAME, lambda d: d["adds"][0]["patches"][0].update(change))
                with self.assertRaises(profile_plan.Refused) as caught:
                    plan(root)
                self.assertIn(ID, str(caught.exception))

    def run_patch(self, directory: Path, text: str, line: str):
        target = directory / "extension.js"
        target.write_text(text, encoding="utf-8")
        return target, subprocess.run(["perl", str(ROOT / "docker" / "profile" / "apply_patches.pl"), line.replace("@", str(target))],
                                      capture_output=True, text=True, stdin=subprocess.DEVNULL, check=False)

    def line(self, original: str, replaced: str, old="aa", new="bb", **over) -> str:
        sha = lambda t: hashlib.sha256(t.encode()).hexdigest()
        fields = {"before": sha(original), "after": sha(replaced), "old": old, "new": new}
        fields.update(over)
        return f"@|{fields['before']}|{fields['after']}|{fields['old']}|{fields['new']}"

    def test_the_right_file_is_patched_and_the_wrong_one_is_refused_by_name_and_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            target, done = self.run_patch(directory, "xaayaaz", self.line("xaayaaz", "xbbybbz"))
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(target.read_text(), "xbbybbz")
            for label, text, line in (
                    ("a file that is not the pinned one", "xaayaaz!", self.line("xaayaaz", "xbbybbz!")),
                    ("a text that does not occur", "xxx", self.line("xxx", "xxx")),
                    ("a result that is not the pinned one", "xaay", self.line("xaay", "something else"))):
                with self.subTest(label):
                    target, done = self.run_patch(directory, text, line)
                    self.assertNotEqual(done.returncode, 0)
                    self.assertIn("patch ", done.stderr)
                    self.assertIn("extension.js", done.stderr)
                    self.assertEqual(target.read_text(), text)


class TheBases(unittest.TestCase):
    def test_the_extension_moves_no_base_tag_and_only_its_profiles_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = context(tmp)
            before = test_profile.base_tags(root)
            tag, other = plan(root).tag, profile_plan.plan(root, "jvm-frameworks", "editor", [], AMD64).tag
            test_profile.edit_profile(root, NAME, lambda d: d["adds"][0]["settings"].update({"kotlin.trace.server": "off"}))
            self.assertEqual(test_profile.base_tags(root), before)
            self.assertNotEqual(plan(root).tag, tag)
            self.assertEqual(profile_plan.plan(root, "jvm-frameworks", "editor", [], AMD64).tag, other)

    def test_the_recorded_editor_tags_are_the_baselines(self):
        for runtimes, name in baseline.SETS.items():
            with self.subTest(runtimes=runtimes):
                names = [n for n in runtimes.split(",") if n]
                tag = profile_plan.base_plan(ROOT, "editor", names, AMD64).tag
                self.assertEqual(tag, f"{baseline.REPOSITORY['editor']}:{name}-amd64-{baseline.DIGEST['editor']}")

    def test_the_profile_is_in_no_base_input(self):
        self.assertNotIn(profile_plan.PROFILES_DIR, profile_plan.editor_plan.OWN_INPUTS)
        self.assertNotIn(profile_plan.RECIPE, profile_plan.editor_plan.OWN_INPUTS)


class TheRefusals(unittest.TestCase):
    def test_a_wrong_archive_checksum_is_refused_by_name_and_unpacks_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            zipped = Path(tmp) / "server.zip"
            good = archive(zipped)
            bad = ("0" if good[0] != "0" else "1") + good[1:]
            done = subprocess.run([sys.executable, str(ROOT / "docker" / "profile" / "fetch_extension.py"),
                                   f"{ID}|{zipped.as_uri()}|{bad}", str(Path(tmp) / "out")],
                                  capture_output=True, text=True, stdin=subprocess.DEVNULL, check=False)
            self.assertEqual(done.returncode, 1)
            for named in (ID, good, bad):
                self.assertIn(named, done.stderr)
            self.assertFalse((Path(tmp) / "out" / ID).exists())

    def test_the_right_checksum_unpacks_the_archive_and_keeps_the_executable_bit(self):
        with tempfile.TemporaryDirectory() as tmp:
            zipped = Path(tmp) / "server.zip"
            good = archive(zipped)
            self.assertEqual(fetch_extension.main([f"{ID}|{zipped.as_uri()}|{good}", str(Path(tmp) / "out")]), 0)
            run = Path(tmp) / "out" / ID / "server" / "bin" / "run"
            self.assertTrue(run.stat().st_mode & stat.S_IXUSR)
            self.assertEqual((Path(tmp) / "out" / ID / "server" / "lib" / "a.jar").read_text(), "jar")

    def test_a_member_outside_the_archives_directory_is_refused(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zipped:
            zipped.writestr("../escape", "x")
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            fetch_extension.unpack(buffer.getvalue(), Path(tmp) / "out")
        self.assertFalse((Path(tmp) / "escape").exists())

    def test_a_tar_archive_is_unpacked_without_its_top_directory_and_keeps_modes_and_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src" / "jdk-9"
            (source / "bin").mkdir(parents=True)
            (source / "bin" / "java").write_text("#!/bin/sh\n")
            (source / "bin" / "java").chmod(0o755)
            (source / "bin" / "alias").symlink_to("java")
            tarball = Path(tmp) / "jdk.tar.gz"
            with tarfile.open(tarball, "w:gz") as packed:
                packed.add(source, arcname="jdk-9")
            good = hashlib.sha256(tarball.read_bytes()).hexdigest()
            self.assertEqual(fetch_extension.main([f"{JDK}|{tarball.as_uri()}|{good}|1", str(Path(tmp) / "out")]), 0)
            java = Path(tmp) / "out" / JDK / "bin" / "java"
            self.assertTrue(java.stat().st_mode & stat.S_IXUSR)
            self.assertEqual((Path(tmp) / "out" / JDK / "bin" / "alias").readlink(), Path("java"))
            self.assertFalse((Path(tmp) / "out" / JDK / "jdk-9").exists())

    def test_a_tar_member_or_link_that_leaves_the_archives_directory_is_refused(self):
        for label, add in (("a path", lambda t: t.addfile(tarfile.TarInfo("../escape"))),
                           ("a link", lambda t: t.addfile(self.link("x/link", "../../outside")))):
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                buffer = io.BytesIO()
                with tarfile.open(fileobj=buffer, mode="w:gz") as packed:
                    add(packed)
                with self.assertRaises(ValueError):
                    fetch_extension.unpack(buffer.getvalue(), Path(tmp) / "out", 0, "tar")
                self.assertFalse((Path(tmp) / "escape").exists())

    @staticmethod
    def link(name: str, target: str) -> tarfile.TarInfo:
        info = tarfile.TarInfo(name)
        info.type, info.linkname = tarfile.SYMTYPE, target
        return info

    def test_an_archive_for_another_platform_is_refused_by_name(self):
        with self.assertRaises(profile_plan.Refused) as caught:
            profile_plan.plan(ROOT, NAME, "editor", [], "linux/arm64")
        self.assertIn(JDK, str(caught.exception))
        self.assertIn("linux/amd64", str(caught.exception))

    def test_no_lines_fetch_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(fetch_extension.main(["", str(Path(tmp) / "out")]), 0)
            self.assertEqual(list((Path(tmp) / "out").iterdir()), [])

    def test_a_placeholder_url_or_checksum_is_unpinned_and_a_build_is_refused_by_name(self):
        for field, value in (("url", "https://example.invalid/TO-BE-PINNED/server.zip"), ("sha256", "TO-BE-PINNED")):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                root = context(tmp)
                test_profile.edit_profile(root, NAME, lambda d: d["adds"][0].update({field: value}))
                self.assertEqual(profile_plan.unpinned(profile_plan.load(root, NAME)), [ID])
                code, err = run_main(root)
                self.assertEqual(code, 2)
                self.assertIn(ID, err)

    def test_an_entry_that_cannot_be_installed_is_refused_by_name(self):
        wrong = {"an image the profile is not built for": {"images": ["runner"]}, "no images": {"images": []},
                 "an id that is a path": {"id": "../x"}, "an http url": {"url": "http://example.invalid/server.zip"},
                 "settings that are a list": {"settings": ["a"]}}
        for label, change in wrong.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                root = context(tmp)
                test_profile.edit_profile(root, NAME, lambda d: d["adds"][0].update(change))
                with self.assertRaises(profile_plan.Refused) as caught:
                    plan(root)
                self.assertIn("editor-extension", str(caught.exception))

    def test_the_real_tree_reaches_the_docker_command_with_the_recipe_context(self):
        with mock.patch.object(profile_build.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            self.assertEqual(profile_build.main(["--profile", NAME, "--image", "editor", "--platform", AMD64,
                                                 "--base-digest", IMAGE_DIGEST]), 0)
        command = run.call_args.args[0]
        self.assertIn(f"profile-recipe={ROOT / 'docker' / 'profile'}", command)
        self.assertTrue(any(a.startswith("PROFILE_EXTENSIONS=" + ID) for a in command))
        self.assertTrue(any(a.startswith("FETCH_IMAGE=python:") and "@sha256:" in a for a in command))


class TheRecipe(unittest.TestCase):
    def test_the_recipe_fetches_checks_installs_and_seeds_in_that_order(self):
        text = (ROOT / profile_plan.DOCKERFILE).read_text(encoding="utf-8")
        self.assertEqual(profile_plan.runner_plan.dockerfile_findings(text), [])
        order = [text.index(step) for step in ("FROM ${FETCH_IMAGE} AS fetch", "fetch_extension.py",
                                               "COPY --from=fetch /fetched /opt/profile/editor-extensions",
                                               "/opt/code-server/seed/settings.json", "grep -q '@runtime kotlin'")]
        self.assertEqual(order, sorted(order))

    def test_the_root_only_steps_hand_back_the_bases_own_user(self):
        text = (ROOT / profile_plan.DOCKERFILE).read_text(encoding="utf-8")
        users = re.findall(r"^USER (.+)$", text, re.M)
        self.assertEqual(users, ["root", "${PROFILE_RESTORE_USER}"])
        self.assertEqual(plan(ROOT, "editor").build_args["PROFILE_RESTORE_USER"], "1000")
        self.assertEqual(profile_plan.plan(ROOT, "fixture-libs", "runner", [], AMD64).build_args["PROFILE_RESTORE_USER"], "root")

    def test_the_patches_are_applied_after_the_install_and_by_the_recipes_own_script(self):
        text = (ROOT / profile_plan.DOCKERFILE).read_text(encoding="utf-8")
        self.assertLess(text.index("COPY --from=fetch"), text.index("apply_patches.pl"))
        self.assertTrue((ROOT / "docker" / "profile" / "apply_patches.pl").is_file())

    def test_the_read_only_pass_does_not_rewrite_the_installed_extensions(self):
        """A recursive chmod over /opt/profile would copy every installed file into a layer of its own."""
        text = (ROOT / profile_plan.DOCKERFILE).read_text(encoding="utf-8")
        self.assertNotRegex(text, r"chmod -R [^\n;]*/opt/profile\s*(;|$)")
        self.assertIn("chmod -R a+rX,a-w /opt/profile/gradle-ro-cache", text)

    def test_the_recipe_chooses_no_version_and_installs_nowhere_but_under_the_profile(self):
        text = (ROOT / profile_plan.DOCKERFILE).read_text(encoding="utf-8")
        self.assertNotIn("github.com", text)
        self.assertNotIn("curl", text)
        self.assertIn(profile_plan.EXTENSION_ROOT, text)


if __name__ == "__main__":
    unittest.main()
