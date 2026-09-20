"""The workbench lockdown extension (TC-04) — no Docker needed.

Run from the component root: `python3 -m unittest discover -s tests -v`.
Every clause is asserted BOTH ways: the real artifact passes, and a planted
violation is caught. The extension itself runs under `node` against a stub
`vscode` module with the timers replaced, so its retry schedule is read
exactly rather than waited out; the image tests
(`tests/test_editor_image.py`, `tests/test_editor_selection_image.py`) read
the installed list off real containers.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDITOR = ROOT / "docker" / "editor"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(EDITOR))
sys.path.insert(0, str(ROOT / "lockdown"))

import build_inputs  # noqa: E402
import editor_plan  # noqa: E402
import lockdown  # noqa: E402

runner_plan = editor_plan.runner_plan
SOURCE = ROOT / editor_plan.LOCKDOWN
MANIFEST = json.loads((SOURCE / lockdown.MANIFEST).read_text(encoding="utf-8"))
LOCK = lockdown.identity(SOURCE)
README = (ROOT / "README.md").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / editor_plan.DOCKERFILE).read_text(encoding="utf-8")
PINS = runner_plan.load(ROOT)
EPINS = editor_plan.load(ROOT)
DIGEST = "0" * 64
#: What the extension closes, in order, and when it closes again — the
#: extraction source's behaviour, kept as literals so a change to either is a
#: decision and not a drift.
CONFINE = [
    "workbench.action.closeOtherEditors",
    "workbench.action.closeSidebar",
    "workbench.action.closePanel",
    "workbench.action.closeAuxiliaryBar",
]
RETRIES = [250, 750, 2000, 6000, 12000]

VSCODE_STUB = """'use strict';
const calls = [];
const api = {
  commands: {
    executeCommand: async (command) => {
      calls.push(command);
      if (process.env.FAIL_ON === command) { throw new Error('not in this build'); }
    },
  },
  workspace: {
    onDidChangeConfiguration: (fn) => {
      api.__listener = fn;
      return { dispose: () => { api.__disposed = true; } };
    },
  },
  __calls: calls,
};
module.exports = api;
"""

HARNESS = """'use strict';
const scheduled = [];
global.setTimeout = (fn, ms) => { const timer = { fn, ms, cleared: false }; scheduled.push(timer); return timer; };
global.clearTimeout = (timer) => { if (timer && typeof timer === 'object') { timer.cleared = true; } };
const vscode = require('vscode');
const extension = require('./extension.js');
const drain = () => new Promise((resolve) => setImmediate(resolve));

(async () => {
  const subscriptions = [];
  extension.activate({ subscriptions });
  await drain();
  const startup = vscode.__calls.splice(0);
  const delays = scheduled.map((timer) => timer.ms);
  scheduled[0].fn();
  await drain();
  const retry = vscode.__calls.splice(0);
  const asked = [];
  vscode.__listener({ affectsConfiguration: (s) => { asked.push(s); return false; } });
  await drain();
  const unrelated = vscode.__calls.splice(0);
  vscode.__listener({ affectsConfiguration: (s) => { asked.push(s); return true; } });
  await drain();
  const related = vscode.__calls.splice(0);
  for (const subscription of subscriptions) { subscription.dispose(); }
  const pending = scheduled.filter((timer) => !timer.cleared).length;
  console.log(JSON.stringify({
    startup, delays, retry, asked, unrelated, related, pending,
    exports: Object.keys(extension).sort(), section: extension.SECTION,
    disposed: vscode.__disposed === true,
  }));
})();
"""


def planted_manifest(**changes) -> dict:
    manifest = copy.deepcopy(MANIFEST)
    manifest.update(changes)
    return manifest


def planted_root(tmp: str) -> Path:
    """A copy of the build's inputs, never touching the tree."""
    return build_inputs.copy_inputs(tmp)


class TheManifest(unittest.TestCase):
    """The identity's one home, and the positive rules that keep it the framework's."""

    def test_the_real_manifest_is_well_formed_and_names_the_documented_identity(self):
        self.assertEqual(lockdown.manifest_findings(MANIFEST), [])
        self.assertEqual(LOCK.id, f"{MANIFEST['publisher']}.{MANIFEST['name']}")
        self.assertEqual(LOCK.expected, f"{LOCK.id}@{MANIFEST['version']}")
        self.assertEqual(LOCK.filename, f"{LOCK.expected.replace('@', '-')}.vsix")
        self.assertEqual(LOCK.section, f"{lockdown.PUBLISHER}.practice")

    def test_a_publisher_that_is_not_this_frameworks_is_found_naming_it(self):
        found = lockdown.manifest_findings(planted_manifest(publisher="example"))
        self.assertIn("the publisher is 'example'", " ".join(found))

    def test_a_setting_outside_the_publishers_namespace_is_found_naming_it(self):
        manifest = copy.deepcopy(MANIFEST)
        properties = manifest["contributes"]["configuration"]["properties"]
        properties["example.practice.main"] = properties.pop(f"{lockdown.PUBLISHER}.practice.main")
        found = " ".join(lockdown.manifest_findings(manifest))
        self.assertIn("example.practice.main", found)
        self.assertIn("belongs to no consumer", found)

    def test_settings_spanning_two_sections_are_found_naming_both(self):
        manifest = copy.deepcopy(MANIFEST)
        properties = manifest["contributes"]["configuration"]["properties"]
        properties[f"{lockdown.PUBLISHER}.other.key"] = {"type": "string"}
        found = " ".join(lockdown.manifest_findings(manifest))
        self.assertIn(f"{lockdown.PUBLISHER}.other", found)
        self.assertIn(LOCK.section, found)

    def test_contributing_no_setting_leaves_no_section_and_is_found(self):
        manifest = copy.deepcopy(MANIFEST)
        manifest["contributes"]["configuration"]["properties"] = {}
        self.assertIn("declares no section", " ".join(lockdown.manifest_findings(manifest)))

    def test_a_missing_key_and_another_activation_event_are_each_found(self):
        for key in ("name", "publisher", "version", "main"):
            with self.subTest(key=key):
                manifest = copy.deepcopy(MANIFEST)
                del manifest[key]
                self.assertIn(f"'{key}' is missing", " ".join(lockdown.manifest_findings(manifest)))
        found = lockdown.manifest_findings(planted_manifest(activationEvents=["onLanguage:java"]))
        self.assertIn("onStartupFinished", " ".join(found))

    def test_identity_refuses_a_manifest_with_a_finding_rather_than_returning_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copy(SOURCE / "extension.js", root / "extension.js")
            (root / lockdown.MANIFEST).write_text(json.dumps(planted_manifest(publisher="example")),
                                                  encoding="utf-8")
            with self.assertRaises(lockdown.Refused) as refused:
                lockdown.identity(root)
            self.assertIn("the publisher is 'example'", str(refused.exception))


class ThePackedVsix(unittest.TestCase):
    """A zip with a manifest, written with the standard library and no marketplace tool."""

    def packed(self, root: Path = SOURCE, name: str | None = None) -> tuple[Path, zipfile.ZipFile]:
        target = Path(self.tmp) / (name or lockdown.identity(root).filename)
        lockdown.pack(root, target)
        return target, zipfile.ZipFile(target)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_it_holds_the_gallery_manifest_the_content_types_and_the_extension(self):
        _, archive = self.packed()
        self.assertEqual(sorted(archive.namelist()),
                         ["[Content_Types].xml", "extension.vsixmanifest",
                          "extension/extension.js", "extension/package.json"])
        manifest = archive.read("extension.vsixmanifest").decode("utf-8")
        publisher, name = LOCK.id.split(".", 1)
        self.assertIn(f'Id="{name}" Version="{LOCK.version}" Publisher="{publisher}"', manifest)
        self.assertEqual(json.loads(archive.read("extension/package.json")), MANIFEST)
        self.assertEqual(archive.read("extension/extension.js"), (SOURCE / "extension.js").read_bytes())

    def test_the_same_inputs_give_the_same_bytes_and_a_changed_script_gives_others(self):
        """A timestamp of the moment would move the install layer for no reason."""
        target, _ = self.packed()
        first = target.read_bytes()
        target.unlink()
        self.assertEqual(self.packed()[0].read_bytes(), first)
        root = Path(self.tmp) / "changed"
        shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("__pycache__"))
        path = root / "extension.js"
        path.write_text(path.read_text(encoding="utf-8") + "\n/* a change */\n", encoding="utf-8")
        changed = Path(self.tmp) / "changed.dir"
        changed.mkdir()
        lockdown.pack(root, changed / LOCK.filename)
        self.assertNotEqual((changed / LOCK.filename).read_bytes(), first)

    def test_a_target_the_manifest_does_not_name_is_refused_naming_both(self):
        with self.assertRaises(lockdown.Refused) as refused:
            lockdown.pack(SOURCE, Path(self.tmp) / "practice.vsix")
        self.assertIn("practice.vsix", str(refused.exception))
        self.assertIn(LOCK.filename, str(refused.exception))

    def test_every_script_beside_the_manifest_is_packed_not_only_main(self):
        root = Path(self.tmp) / "with-helper"
        shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("__pycache__"))
        (root / "helper.js").write_text("module.exports = {};\n", encoding="utf-8")
        target = Path(self.tmp) / lockdown.identity(root).filename
        lockdown.pack(root, target)
        self.assertIn("extension/helper.js", zipfile.ZipFile(target).namelist())

    def test_a_main_that_is_not_beside_the_manifest_is_refused_naming_it(self):
        root = Path(self.tmp) / "no-main"
        shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("__pycache__"))
        (root / "extension.js").unlink()
        with self.assertRaises(lockdown.Refused) as refused:
            lockdown.pack(root, Path(self.tmp) / LOCK.filename)
        self.assertIn("extension.js", str(refused.exception))

    def test_the_cli_packs_it_and_refuses_a_target_the_manifest_does_not_name(self):
        good = subprocess.run([sys.executable, str(SOURCE / "lockdown.py"), str(SOURCE),
                               str(Path(self.tmp) / LOCK.filename)], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertIn(LOCK.expected, good.stdout)
        bad = subprocess.run([sys.executable, str(SOURCE / "lockdown.py"), str(SOURCE),
                              str(Path(self.tmp) / "other.vsix")], capture_output=True, text=True,
                             stdin=subprocess.DEVNULL)
        self.assertEqual(bad.returncode, 2)
        self.assertIn("refused:", bad.stderr)


class TheDerivedIdentity(unittest.TestCase):
    """One place carries the id; the file name, the plan, the README and the image agree with it."""

    def test_no_source_file_writes_the_identifier_out_by_hand(self):
        for path in (EDITOR / "editor_plan.py", EDITOR / "build.py", ROOT / editor_plan.DOCKERFILE,
                     SOURCE / "extension.js", SOURCE / "lockdown.py"):
            with self.subTest(path=path.name):
                found = LOCK.id in path.read_text(encoding="utf-8")
                self.assertFalse(found, f"{path.name} writes the identifier out instead of deriving it")

    def test_the_readme_documents_exactly_the_id_a_consumer_pins(self):
        section = README.split("### The workbench lockdown", 1)[1].split("\n### ", 1)[0]
        self.assertIn(LOCK.id, section)
        self.assertIn(f"{lockdown.PUBLISHER}.practice.main", section)
        self.assertNotIn("docker run", section)
        self.assertEqual(runner_plan.run_line_findings(README), [])

    def test_the_plan_names_the_packed_file_and_expects_the_packed_id(self):
        runner = runner_plan.plan(PINS, editor_plan.selection(PINS, ["java"]), "linux/amd64", DIGEST)
        built = editor_plan.plan(PINS, EPINS, runner, DIGEST)
        self.assertEqual(built.build_args["LOCKDOWN_VSIX"], LOCK.filename)
        self.assertIn(LOCK.expected, built.build_args["EXPECTED_EXTENSIONS"].split())

    def test_a_renamed_manifest_moves_the_file_name_and_the_expected_id_together(self):
        """The other way: renaming it in its one home moves every derived name at once."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "renamed"
            shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("__pycache__"))
            path = root / lockdown.MANIFEST
            path.write_text(path.read_text(encoding="utf-8").replace('"practice-focus"', '"reading-focus"'),
                            encoding="utf-8")
            renamed = lockdown.identity(root)
            self.assertEqual(renamed.id, f"{lockdown.PUBLISHER}.reading-focus")
            self.assertEqual(renamed.filename, f"{renamed.id}-{renamed.version}.vsix")
            self.assertEqual(renamed.expected, f"{renamed.id}@{renamed.version}")

    def test_the_dockerfile_packs_it_in_its_own_stage_and_installs_the_packed_file(self):
        self.assertIn("FROM ${FETCH_IMAGE} AS lockdown", DOCKERFILE)
        self.assertIn('python3 /lockdown/lockdown.py /lockdown "/packed/${LOCKDOWN_VSIX}"', DOCKERFILE)
        self.assertIn("from=lockdown,source=/packed,target=/tmp/lockdown", DOCKERFILE)
        self.assertIn("for vsix in /tmp/fetch/*.vsix /tmp/lockdown/*.vsix; do", DOCKERFILE)
        self.assertEqual(editor_plan.install_findings(DOCKERFILE), [])
        self.assertEqual(runner_plan.dockerfile_findings(DOCKERFILE), [])

    def test_the_editors_tag_moves_when_the_extension_changes_and_no_runner_tag_does(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = planted_root(tmp)
            before = editor_plan.inputs_digest(root)
            runner_before = runner_plan.inputs_digest(root)
            path = root / editor_plan.LOCKDOWN / "extension.js"
            path.write_text(path.read_text(encoding="utf-8") + "\n/* a change */\n", encoding="utf-8")
            self.assertNotEqual(editor_plan.inputs_digest(root), before)
            self.assertEqual(runner_plan.inputs_digest(root), runner_before)

    def test_a_manifest_the_framework_does_not_publish_is_refused_before_docker_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = planted_root(tmp)
            path = root / editor_plan.LOCKDOWN / lockdown.MANIFEST
            path.write_text(path.read_text(encoding="utf-8").replace('"studyforge"', '"example"'), encoding="utf-8")
            env = {"PATH": "/nonexistent", "PYTHONDONTWRITEBYTECODE": "1"}
            refused = subprocess.run([sys.executable, str(root / "docker" / "editor" / "build.py"),
                                      "--root", str(root)], env=env, capture_output=True, text=True,
                                     stdin=subprocess.DEVNULL)
            self.assertEqual(refused.returncode, 2, refused.stderr)
            self.assertIn("the lockdown extension", refused.stderr)
            self.assertIn("the publisher is 'example'", refused.stderr)


class TheExtensionBehaviour(unittest.TestCase):
    """The ported CommonJS, run under `node` against a stub `vscode` with the timers replaced."""

    def setUp(self):
        self.node = shutil.which("node")
        if not self.node:
            self.skipTest("no node on PATH; the image tests install the packed extension for real")
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for path in lockdown.sources(SOURCE):
            shutil.copy(path, Path(self.tmp) / path.name)
        stub = Path(self.tmp) / "node_modules" / "vscode"
        stub.mkdir(parents=True)
        (stub / "package.json").write_text(json.dumps({"name": "vscode", "version": "1.0.0",
                                                       "main": "index.js"}), encoding="utf-8")
        (stub / "index.js").write_text(VSCODE_STUB, encoding="utf-8")
        (Path(self.tmp) / "harness.js").write_text(HARNESS, encoding="utf-8")

    def ran(self, **env) -> dict:
        done = subprocess.run([self.node, str(Path(self.tmp) / "harness.js")], capture_output=True, text=True,
                              cwd=self.tmp, env={**os.environ, **env}, stdin=subprocess.DEVNULL)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_activation_closes_every_surface_in_order_and_schedules_the_decaying_retries(self):
        read = self.ran()
        self.assertEqual(read["startup"], CONFINE)
        self.assertEqual(read["delays"], RETRIES)
        self.assertEqual(read["retry"], CONFINE)
        self.assertEqual(read["exports"], ["CONFINE", "RETRIES", "SECTION", "activate", "deactivate"])

    def test_it_watches_its_own_section_and_reapplies_only_when_that_section_changed(self):
        read = self.ran()
        self.assertEqual(read["section"], LOCK.section)
        self.assertEqual(set(read["asked"]), {LOCK.section})
        self.assertEqual(read["unrelated"], [], "a change elsewhere closes nothing")
        self.assertEqual(read["related"], CONFINE)

    def test_disposing_the_context_cancels_every_pending_retry_and_the_listener(self):
        read = self.ran()
        self.assertEqual(read["pending"], 0)
        self.assertTrue(read["disposed"])

    def test_a_command_this_workbench_does_not_have_does_not_stop_the_others(self):
        read = self.ran(FAIL_ON=CONFINE[1])
        self.assertEqual(read["startup"], CONFINE)

    def test_the_section_it_watches_is_the_namespace_of_every_setting_it_contributes(self):
        keys = MANIFEST["contributes"]["configuration"]["properties"]
        section = self.ran()["section"]
        self.assertTrue(keys)
        for key in keys:
            with self.subTest(key=key):
                self.assertTrue(key.startswith(section + "."), key)


if __name__ == "__main__":
    unittest.main()
