"""The editor's plan, pins and static checks — no Docker needed.

Run from the component root: `python3 -m unittest discover -s tests -v`.
Every rule is asserted BOTH ways: the real file passes, and a planted
violation is caught.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDITOR = ROOT / "docker" / "editor"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(EDITOR))

import build_inputs  # noqa: E402
import editor_plan  # noqa: E402

runner_plan = editor_plan.runner_plan
_spec = importlib.util.spec_from_file_location("editor_build", EDITOR / "build.py")
editor_build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(editor_build)

PINS = runner_plan.load(ROOT)
EPINS = editor_plan.load(ROOT)
DIGEST = "0" * 64
DOCKERFILE = (ROOT / editor_plan.DOCKERFILE).read_text(encoding="utf-8")
SEED = (EDITOR / "seed" / "settings.json").read_text(encoding="utf-8")
ENTRYPOINT = (EDITOR / "entrypoint.sh").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
#: The lockdown extension every set installs; its own tests are tests/test_lockdown.py.
LOCKDOWN = editor_plan.lockdown_identity(ROOT)


def runner_for(platform: str = "linux/amd64", pins: dict = PINS) -> runner_plan.Plan:
    return runner_plan.plan(pins, list(editor_plan.DEFAULT_SET), platform, DIGEST)


def runner_for_names(names, platform: str = "linux/amd64") -> runner_plan.Plan:
    return runner_plan.plan(PINS, editor_plan.selection(PINS, names), platform, DIGEST)


def planned(epins: dict = EPINS, platform: str = "linux/amd64", pins: dict = PINS) -> editor_plan.EditorPlan:
    return editor_plan.plan(pins, epins, runner_for(platform, pins), DIGEST)


def without_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(("#", "//")))


class TheEditorsPins(unittest.TestCase):
    def test_the_real_pins_are_well_formed(self):
        self.assertEqual(editor_plan.pins_findings(EPINS), [])

    def test_each_planted_defect_is_found(self):
        plants = {
            "base digest": lambda p: p["base"].update(digest="sha256:short"),
            "typescript sha": lambda p: p["typescript"].update(sha256="abc"),
            "typescript integrity": lambda p: p["typescript"].pop("integrity"),
            "readline deb": lambda p: p["readline"]["debs"]["amd64"].pop("readline-common"),
            "vsix sha": lambda p: p["extensions"]["fwcd.kotlin"]["files"]["universal"].update(sha256="0"),
            "vsix url off version": lambda p: p["extensions"]["fwcd.kotlin"].update(version="9.9.9"),
            "no source": lambda p: p["extensions"]["redhat.java"].update(sources=[]),
            "single-source unexplained": lambda p: p["extensions"]["ms-python.python"].pop("why_single"),
            "single_source missing": lambda p: p["typescript"].pop("single_source"),
        }
        for label, plant in plants.items():
            with self.subTest(plant=label):
                planted = copy.deepcopy(EPINS)
                plant(planted)
                self.assertNotEqual(editor_plan.pins_findings(planted), [])

    def test_no_runtime_version_is_chosen_in_the_editors_pins(self):
        """pins.json is the ONE place a runtime version is chosen."""
        self.assertEqual(set(EPINS) & {"runtimes", "platforms"}, set())
        self.assertEqual(set(EPINS), {"pins_api", "about", "base", "typescript", "readline", "kotlin_language_server_jdk", "kotlin_language_server", "face", "extensions"})

    def test_the_readline_snapshot_is_the_one_pins_json_already_uses(self):
        self.assertEqual(EPINS["readline"]["snapshot"], PINS["runtimes"]["sqlite"]["snapshot"])


class TheExtensionSet(unittest.TestCase):
    def test_every_required_id_is_pinned_and_the_plan_expects_exactly_the_pins(self):
        expected = planned().build_args["EXPECTED_EXTENSIONS"].split()
        self.assertEqual(expected, sorted([f"{e}@{EPINS['extensions'][e]['version']}" for e in EPINS["extensions"]]
                                          + [LOCKDOWN.expected]))
        required = {ext for exts in editor_plan.REQUIRED_EXTENSIONS.values() for ext in exts}
        self.assertLessEqual(required, set(EPINS["extensions"]))

    def test_removing_a_required_pin_is_refused_naming_it(self):
        for ext in sorted(ext for exts in editor_plan.REQUIRED_EXTENSIONS.values() for ext in exts):
            with self.subTest(extension=ext):
                planted = copy.deepcopy(EPINS)
                del planted["extensions"][ext]
                with self.assertRaises(editor_plan.Refused) as refused:
                    planned(planted)
                self.assertIn(ext, str(refused.exception))

    def test_removing_the_pin_is_refused_by_the_build_before_docker_starts(self):
        """The CLI's refusal: exit 2 with no Docker on PATH, and the real pins print a tag the same way."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_inputs.copy_inputs(tmp)
            planted = copy.deepcopy(EPINS)
            del planted["extensions"]["fwcd.kotlin"]
            (root / "editor-pins.json").write_text(json.dumps(planted), encoding="utf-8")
            env = {"PATH": "/nonexistent", "PYTHONDONTWRITEBYTECODE": "1"}
            command = [sys.executable, str(root / "docker" / "editor" / "build.py"), "--root", str(root)]
            refused = subprocess.run(command, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
            self.assertEqual(refused.returncode, 2, refused.stderr)
            self.assertIn("fwcd.kotlin", refused.stderr)
            shutil.copy(ROOT / "editor-pins.json", root / "editor-pins.json")
            real = subprocess.run(command + ["--print-tag"], env=env, capture_output=True, text=True,
                                  stdin=subprocess.DEVNULL)
            self.assertEqual(real.returncode, 0, real.stderr)
            self.assertTrue(real.stdout.startswith(editor_plan.REPOSITORY + ":"))

    def test_an_unpinned_dependency_or_pack_member_is_refused(self):
        planted = copy.deepcopy(EPINS)
        planted["extensions"]["fwcd.kotlin"]["depends"] = ["example.missing"]
        with self.assertRaises(editor_plan.Refused):
            planned(planted)
        planted = copy.deepcopy(EPINS)
        planted["extensions"]["ms-python.python"]["pack_absent"] = {}
        with self.assertRaises(editor_plan.Refused):
            planned(planted)
        planted = copy.deepcopy(EPINS)
        planted["extensions"]["vscjava.vscode-java-test"]["depends"] = []
        planned(planted)  # dropping a recorded dependency is not refused here; the image check catches it

    def test_each_architecture_takes_its_own_file_and_falls_back_to_universal(self):
        for platform, target in (("linux/amd64", "linux-x64"), ("linux/arm64", "linux-arm64")):
            with self.subTest(platform=platform):
                fetch = planned(platform=platform).build_args["FETCH"]
                self.assertIn(EPINS["extensions"]["ms-python.debugpy"]["files"][target]["sha256"], fetch)
                self.assertIn(EPINS["extensions"]["redhat.java"]["files"]["universal"]["sha256"], fetch)
        planted = copy.deepcopy(EPINS)
        del planted["extensions"]["ms-python.debugpy"]["files"]["linux-arm64"]
        with self.assertRaises(editor_plan.Refused):
            planned(planted, platform="linux/arm64")

    def test_any_other_platform_is_refused_by_name(self):
        with self.assertRaises(editor_plan.Refused):
            runner_for("linux/riscv64")

    def test_every_fetched_file_carries_its_recorded_sha256(self):
        for line in planned().build_args["FETCH"].splitlines():
            name, url, sha256 = line.split("|")
            with self.subTest(file=name):
                self.assertRegex(sha256, r"^[0-9a-f]{64}$")
                self.assertTrue(url.startswith("https://"))


class TheRuntimes(unittest.TestCase):
    def test_the_editor_runs_the_runners_checks_and_expects_the_runners_opt(self):
        runner, editor = runner_for(), planned()
        self.assertTrue(editor.build_args["CHECKS"].startswith(runner.build_args["CHECKS"]))
        self.assertIn(f"typescript|tsc --version|Version {EPINS['typescript']['version']}", editor.build_args["CHECKS"])
        self.assertEqual(editor.build_args["OPT_EXPECTED"].split(),
                         sorted(runner.build_args["OPT_EXPECTED"].split() + ["code-server"]))
        self.assertEqual(editor.build_args["RUNNER_IMAGE"], runner.tag)

    def test_a_runtime_version_moves_only_through_pins_json(self):
        bumped = copy.deepcopy(PINS)
        bumped["runtimes"]["node"]["version"] = "99.0.0"
        self.assertIn("node|node --version|v99.0.0", planned(pins=bumped).build_args["CHECKS"])
        self.assertNotIn("v99.0.0", planned().build_args["CHECKS"])

    def test_the_java_runtime_name_is_derived_from_the_pinned_jdk(self):
        major = PINS["runtimes"]["java"]["version"].split(".")[0]
        self.assertEqual(planned().build_args["JAVA_RUNTIME"], f"JavaSE-{major}")
        bumped = copy.deepcopy(PINS)
        bumped["runtimes"]["java"]["version"] = "31.0.1+2"
        self.assertEqual(planned(pins=bumped).build_args["JAVA_RUNTIME"], "JavaSE-31")


class TheTag(unittest.TestCase):
    def _copy(self, tmp: str) -> Path:
        return build_inputs.copy_inputs(tmp)

    def test_the_editors_tag_moves_with_every_input_and_the_runners_does_not_move_with_the_editors(self):
        """An editor-only change moves no runner tag; a runner change moves both."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._copy(tmp)
            editor0, runner0 = editor_plan.inputs_digest(root), runner_plan.inputs_digest(root)
            for path in ("editor-pins.json", "docker/editor/seed/settings.json", "prime/warm-maven.sh"):
                with self.subTest(changed=path):
                    with (root / path).open("a", encoding="utf-8") as handle:
                        handle.write("\n")
                    self.assertNotEqual(editor_plan.inputs_digest(root), editor0)
                    self.assertEqual(runner_plan.inputs_digest(root), runner0)
                    editor0 = editor_plan.inputs_digest(root)
            for path in ("pins.json", "docker/minimal/Dockerfile"):
                with self.subTest(changed=path):
                    with (root / path).open("a", encoding="utf-8") as handle:
                        handle.write("\n")
                    self.assertNotEqual(runner_plan.inputs_digest(root), runner0)
                    self.assertNotEqual(editor_plan.inputs_digest(root), editor0)
                    runner0, editor0 = runner_plan.inputs_digest(root), editor_plan.inputs_digest(root)

    def test_the_tag_names_the_editor_the_set_and_the_architecture(self):
        tag = planned().tag
        self.assertRegex(tag, r"^code-server-toolchain/editor:gradle-java-kotlin-node-python-amd64-0{12}$")


class TheKotlinLanguageServerJdk(unittest.TestCase):
    """The Kotlin server runs on a JDK 21 of its own: the runner's JDK 25 crashes its bundled compiler."""

    def test_a_set_with_kotlin_fetches_and_checks_the_jdk_and_a_set_without_it_does_not(self):
        with_kotlin = planned().build_args
        self.assertIn("kotlin-ls-jdk.tgz|", with_kotlin["FETCH"])
        self.assertEqual(with_kotlin["WITH_KOTLIN_LS_JDK"], "yes")
        self.assertIn("kotlin-ls-jdk|", with_kotlin["CHECKS"])
        java_only = editor_plan.plan(PINS, EPINS, runner_for_names(["java"]), DIGEST).build_args
        self.assertEqual(java_only["WITH_KOTLIN_LS_JDK"], "no")
        self.assertNotIn("kotlin-ls-jdk", java_only["FETCH"] + java_only["CHECKS"])

    def test_the_archive_is_pinned_by_sha256_for_both_platforms_and_a_planted_loss_is_found(self):
        self.assertEqual(set(EPINS["kotlin_language_server_jdk"]["files"]), {"linux-x64", "linux-arm64"})
        planted = copy.deepcopy(EPINS)
        planted["kotlin_language_server_jdk"]["files"]["linux-x64"]["sha256"] = "0"
        self.assertNotEqual(editor_plan.pins_findings(planted), [])

    def test_the_setting_is_a_machine_file_written_every_start_and_not_the_users_seed(self):
        self.assertIn("machine-settings.json", DOCKERFILE)
        self.assertIn("Machine/settings.json", ENTRYPOINT)
        self.assertNotIn("kotlin.java.home", SEED)


class TheKotlinLanguageServer(unittest.TestCase):
    """The server is baked in at build time, so the extension never downloads it and the course works offline."""
    LS = EPINS["kotlin_language_server"]

    def test_a_set_with_kotlin_fetches_patches_and_checks_the_server_and_a_set_without_it_does_not(self):
        args = planned().build_args
        self.assertIn("kotlin-ls.zip|" + self.LS["files"]["universal"]["url"] + "|" + self.LS["files"]["universal"]["sha256"],
                      args["FETCH"])
        self.assertEqual(args["WITH_KOTLIN_LS"], "yes")
        self.assertIn("kotlin-ls|", args["CHECKS"])
        self.assertIn("JAVA_HOME=" + EPINS["kotlin_language_server_jdk"]["dir"], self.LS["checks"][0]["command"])
        java_only = editor_plan.plan(PINS, EPINS, runner_for_names(["java"]), DIGEST).build_args
        self.assertEqual(java_only["WITH_KOTLIN_LS"], "no")
        self.assertNotIn("kotlin-ls.zip", java_only["FETCH"])
        self.assertNotIn("kotlin-ls|", java_only["CHECKS"])

    def test_the_machine_settings_point_at_the_server_and_the_jdk_and_stop_the_downloads(self):
        settings = json.loads(planned().build_args["KOTLIN_LS_SETTINGS"])
        self.assertEqual(settings["kotlin.languageServer.path"], self.LS["dir"] + "/bin/kotlin-language-server")
        self.assertEqual(settings["kotlin.java.home"], EPINS["kotlin_language_server_jdk"]["dir"])
        self.assertIs(settings["kotlin.debugAdapter.enabled"], False)

    def test_the_server_release_is_the_one_the_pinned_extension_names_and_each_patch_is_pinned(self):
        self.assertEqual(self.LS["version"], "1.3.13")
        patch = planned().build_args["KOTLIN_LS_PATCHES"].split("|")
        self.assertIn("fwcd.kotlin-" + EPINS["extensions"]["fwcd.kotlin"]["version"], patch[0])
        self.assertEqual(len(patch[1]), 64)
        self.assertEqual(len(patch[2]), 64)

    def test_planted_defects_in_the_server_pin_are_found(self):
        plants = {
            "sha": lambda p: p["kotlin_language_server"]["files"]["universal"].update(sha256="0"),
            "version": lambda p: p["kotlin_language_server"].update(version="9.9.9"),
            "patch hash": lambda p: p["kotlin_language_server"]["patches"][0].update(after="0"),
            "path outside the tree": lambda p: p["kotlin_language_server"]["settings"].update(
                {"kotlin.languageServer.path": "/usr/bin/x"}),
        }
        for label, plant in plants.items():
            with self.subTest(plant=label):
                planted = copy.deepcopy(EPINS)
                plant(planted)
                self.assertNotEqual(editor_plan.pins_findings(planted), [])

    def test_the_dockerfile_unpacks_the_server_in_the_fetch_stage_and_patches_after_the_extensions(self):
        self.assertLess(DOCKERFILE.index("kotlin-ls.zip"), DOCKERFILE.index("AS lockdown"))
        self.assertLess(DOCKERFILE.index("--install-extension"), DOCKERFILE.index("apply_patches.pl"))


class TheDockerfile(unittest.TestCase):
    def test_the_real_dockerfile_chooses_nothing_and_has_no_scratch_stage(self):
        self.assertEqual(runner_plan.dockerfile_findings(DOCKERFILE), [])
        self.assertNotRegex(without_comments(DOCKERFILE), r"(?im)^\s*FROM\s+scratch")

    def test_each_planted_dockerfile_defect_is_found(self):
        for planted in ("\nARG TS_VERSION=6\n", "\nFROM codercom/code-server:latest AS extra\n",
                        "\nFROM scratch AS bare\n"):
            with self.subTest(planted=planted.strip()):
                self.assertNotEqual(runner_plan.dockerfile_findings(DOCKERFILE + planted), [])

    def test_no_extension_is_installed_by_bare_id(self):
        self.assertEqual(editor_plan.install_findings(DOCKERFILE), [])
        planted = DOCKERFILE + "\nRUN code-server --install-extension fwcd.kotlin\n"
        self.assertNotEqual(editor_plan.install_findings(planted), [])

    def test_the_plan_supplies_exactly_the_args_the_dockerfile_declares(self):
        declared = set(re.findall(r"^\s*ARG\s+(\w+)\s*$", DOCKERFILE, re.M))
        self.assertEqual(declared, set(planned().build_args))

    def test_the_install_and_typescript_steps_run_with_no_network(self):
        body = without_comments(DOCKERFILE)
        self.assertIn("--network=none --mount=type=bind,from=fetch", body)
        # Every step that must not reach the network: TypeScript from the pinned
        # tarball, the extension install, the lockdown's pack stage and
        # the prime's offline proof, the code face taken out of its archive
        # and then placed beside the workbench's stylesheet, and the workbench's
        # own AI taken out of its bundles, and the static path's digest.
        offline = ("npm install -g --offline", "--install-extension", "/lockdown/lockdown.py", "prove",
                   "python3 /face.py", "--mount=type=bind,from=face", "/tmp/no_ai.js", "static path: stable-",
                   "kotlin-ls-jdk.tgz", "apply_patches.pl")
        self.assertEqual(body.count("RUN --network=none"), len(offline))
        for needle in offline:
            self.assertIn(needle, body)

    def test_path_is_set_by_env_and_again_by_profile_d_with_the_same_trees(self):
        self.assertRegex(DOCKERFILE, r"(?m)^ENV PATH=\$\{EDITOR_PATH\}$")
        self.assertIn('printf \'%s\\n\' "${PROFILE_D}"', DOCKERFILE)
        args = planned().build_args
        env = args["EDITOR_PATH"].split(":")
        profile = re.search(r"^export PATH=(\S+)$", args["PROFILE_D"], re.M).group(1).split(":")
        self.assertEqual([p for p in env if p.startswith("/opt/")], [p for p in profile if p.startswith("/opt/")])
        self.assertIn("/etc/profile.d/", DOCKERFILE)

    def test_nothing_names_the_extraction_source_or_a_path_outside_the_component(self):
        """No source is named and the extraction is one-way: carried properties, never a cited path."""
        for path in sorted(EDITOR.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                with self.subTest(file=path.name):
                    text = path.read_text(encoding="utf-8").lower()
                    self.assertNotIn("codesignal", text)
                    self.assertNotIn("../", text)


class TheEntrypointAndSeed(unittest.TestCase):
    def test_the_entrypoint_hands_over_to_the_bases_entrypoint_and_has_no_exec_mode(self):
        code = without_comments(ENTRYPOINT)
        # ⭐ The arguments pass through whole, and the two call-home switches
        # follow them, so a consumer's command can add to them and never drop them.
        self.assertEqual(code.strip().splitlines()[-1],
                         'exec /usr/bin/entrypoint.sh "$@" --disable-update-check --disable-telemetry')
        self.assertNotIn('"exec"', code)
        # `find -exec` in the prime's seeding is not a command of its own.
        self.assertEqual(len(re.findall(r"(?m)^\s*exec ", code)), 1)

    def test_the_seed_declares_a_login_terminal_and_derives_the_java_name(self):
        seed = json.loads(re.sub(r"^\s*//.*$", "", SEED, flags=re.M))
        self.assertEqual(seed["terminal.integrated.profiles.linux"]["bash"]["args"], ["-l"])
        self.assertEqual(seed["terminal.integrated.defaultProfile.linux"], "bash")
        self.assertEqual(seed["java.configuration.runtimes"][0]["name"], "@JAVA_RUNTIME@")
        self.assertNotIn("python.testing.pytestArgs", seed)
        self.assertNotRegex(SEED, r"JavaSE-\d")


class TheReadme(unittest.TestCase):
    def test_the_readme_documents_the_editor_with_no_run_line_of_its_own(self):
        """The editor's run shape is `consuming.json`'s; the runner's run-line check stays green."""
        section = README.split("## The editor image", 1)[1].split("\n## ", 1)[0]
        self.assertNotIn("docker run", section)
        self.assertIn("docker/editor/build.py", section)
        self.assertEqual(runner_plan.run_line_findings(README), [])
        self.assertNotEqual(runner_plan.run_line_findings(README + "\ndocker run -p 8080:8080 editor\n"), [])


class TheExtensionVerifier(unittest.TestCase):
    """The build-time verifier, run by any `node` on PATH; the image tests run it for real."""

    def setUp(self):
        self.node = shutil.which("node")
        if not self.node:
            self.skipTest("no node on PATH; the image tests exercise the verifier")

    def _verify(self, listed: list[str], expected: list[str], packages: dict[str, dict]) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmp:
            for folder, package in packages.items():
                (Path(tmp) / folder).mkdir()
                (Path(tmp) / folder / "package.json").write_text(json.dumps(package), encoding="utf-8")
            return subprocess.run([self.node, str(EDITOR / "verify_extensions.js"), tmp, *expected],
                                  input="\n".join(listed) + "\n", capture_output=True, text=True)

    def test_exact_agreement_passes_and_each_difference_is_named(self):
        a = {"a.one-1.0.0": {"publisher": "a", "name": "one"}}
        b = {"b.two-2.0.0": {"publisher": "b", "name": "two", "extensionDependencies": ["a.one"]}}
        both = ["a.one@1.0.0", "b.two@2.0.0"]
        self.assertEqual(self._verify(both, both, a | b).returncode, 0)
        missing = self._verify(["a.one@1.0.0"], ["a.one@1.0.0", "b.two@2.0.0"], a)
        self.assertEqual(missing.returncode, 1)
        self.assertIn("b.two@2.0.0 is pinned but not installed", missing.stderr)
        extra = self._verify(["a.one@1.0.0", "b.two@2.0.0"], ["a.one@1.0.0"], a | b)
        self.assertIn("b.two@2.0.0 is installed but not pinned", extra.stderr)
        unmet = self._verify(["b.two@2.0.0"], ["b.two@2.0.0"], b)
        self.assertEqual(unmet.returncode, 1)
        self.assertIn("b.two depends on a.one, which is not installed", unmet.stderr)


class TheFetcher(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("editor_fetch", EDITOR / "fetch.py")
        self.fetch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.fetch)

    def test_the_recorded_sha256_passes_and_any_other_bytes_are_named(self):
        import hashlib

        data = b"pinned bytes"
        good = hashlib.sha256(data).hexdigest()
        self.assertIsNone(self.fetch.check("a.vsix", data, good))
        self.assertIn("a.vsix", self.fetch.check("a.vsix", data + b"!", good))
        self.assertEqual(self.fetch.parse("a.vsix|https://x/a|" + good + "\n\n"), [("a.vsix", "https://x/a", good)])

    def test_the_request_carries_a_placeholder_and_no_identity(self):
        self.assertEqual(self.fetch.USER_AGENT, "Example/0.1 (+https://example.invalid)")


if __name__ == "__main__":
    unittest.main()
