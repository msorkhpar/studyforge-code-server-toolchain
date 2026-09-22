"""The practice frame is CONFINED — the allow-list, the seed, and the gate (W433).

Run from the component root: `python3 -m unittest discover -s tests -v`.
Everything here is asserted BOTH ways: the real artifact passes, and a planted
violation is caught.

⭐ **The reading this row started from, because every clause below is aimed at
it.** `files.readonlyExclude` is what makes a Submit mean anything — the test
that judges the reader is not theirs to edit — and it is an OBJECT setting,
which VS Code MERGES across scopes. Measured in a real session on
code-server 4.137.0: the workspace value `{"Main.java": true}` became
`{"MainTest.java": true, "Main.java": true}` after a single
`ConfigurationTarget.Global` write, and the user settings file on disk carried
it. ⛔ So a reader who can reach the settings editor can make their own test
writable, and confining the command surface is an INTEGRITY clause rather than
a tidiness one.

⚠️ **The one Docker class here is skipped unless `TC_DOCKER=1`**: it starts
containers and drives a headless browser.

    TC_DOCKER=1 python3 -m unittest tests.test_lockdown_confinement -v
"""

from __future__ import annotations

import json
import os
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
sys.path.insert(0, str(ROOT / "lockdown"))

import cdp  # noqa: E402
import confinement  # noqa: E402
import editor_plan  # noqa: E402
import lockdown  # noqa: E402
import test_lockdown  # noqa: E402

SOURCE = ROOT / editor_plan.LOCKDOWN
LOCK = lockdown.identity(SOURCE)
SEED = ROOT / confinement.SEED
DOCKERFILE = (ROOT / editor_plan.DOCKERFILE).read_text(encoding="utf-8")
ENTRYPOINT = (EDITOR / "entrypoint.sh").read_text(encoding="utf-8")

#: The seven surfaces the reader's own screenshot named, by the command behind
#: each. ⛔ Literals, so a change to the allow-list that re-opened one of them
#: is a failing test and not a drift.
THE_SEVEN = (
    "workbench.action.quickOpen",            # Go to File
    "workbench.action.showCommands",         # Show and Run Commands
    "workbench.action.findInFiles",          # Search for Text
    "workbench.action.quickchat.toggle",     # Open Quick Chat
    "workbench.action.gotoSymbol",           # Go to Symbol in Editor
    "workbench.action.debug.start",          # Start Debugging
    "workbench.action.tasks.runTask",        # Run Task
)
#: Both ways into the settings a reader could change — the editor and the JSON.
THE_SETTINGS = ("workbench.action.openSettings", "workbench.action.openSettingsJson")
#: What a practice must keep. ⚠️ A confinement that breaks these has made the
#: product worse, and this list is the test of that.
THE_PRACTICE = ("cursorLeft", "cursorWordEndRightSelect", "deleteLeft", "undo", "redo", "tab",
                "actions.find", "editor.action.startFindReplaceAction", "editor.action.selectAll",
                "acceptSelectedSuggestion", "workbench.action.files.save")


def node_or_skip(case) -> str:
    found = shutil.which("node")
    if not found:
        case.skipTest("no node on PATH; the image tests run the packed extension for real")
    return found


class TheAllowList(unittest.TestCase):
    """`lockdown/allowed.js` — what a practice may do, and everything derived from it."""

    def ran(self, script: str):
        node = node_or_skip(self)
        done = subprocess.run([node, "-e", f"const allowed = require('{SOURCE / 'allowed.js'}');\n{script}"],
                              capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_the_seven_the_reader_saw_and_both_ways_into_settings_are_refused(self):
        commands = list(THE_SEVEN) + list(THE_SETTINGS)
        answered = self.ran(f"console.log(JSON.stringify({json.dumps(commands)}.filter(allowed.allows)))")
        self.assertEqual(answered, [], f"{answered} are still allowed")

    def test_everything_a_practice_needs_is_allowed(self):
        answered = self.ran(f"console.log(JSON.stringify("
                            f"{json.dumps(list(THE_PRACTICE))}.filter((c) => !allowed.allows(c))))")
        self.assertEqual(answered, [], f"{answered} would be taken away from the reader")

    def test_a_command_the_workbench_gains_is_refused_without_anyone_editing_this(self):
        # ⛔ The property that makes this an allow-list and not a deny-list. A
        # deny-list is wrong the moment the workbench gains a command and
        # nothing says so; this is wrong in the visible direction instead.
        invented = ["workbench.action.openTheNewThing", "workbench.action.chat.openInEditorSession"]
        self.assertEqual(self.ran(f"console.log(JSON.stringify({json.dumps(invented)}.filter(allowed.allows)))"), [])

    def test_a_removal_carries_no_when_so_it_covers_every_clause_the_default_has(self):
        # ⚠️ Measured, and it is the difference between confining a key and
        # confining it only in the state its `when` clause describes: VS Code's
        # resolver treats a removal with no `when` as matching all of them.
        defaults = [{"key": "ctrl+shift+o", "command": "workbench.action.gotoSymbol", "when": "!a && !b"},
                    {"key": "ctrl+shift+o", "command": "workbench.action.gotoSymbol", "when": "other"}]
        answered = self.ran(f"console.log(JSON.stringify(allowed.removals({json.dumps(defaults)})))")
        self.assertEqual(answered, [{"key": "ctrl+shift+o", "command": "-workbench.action.gotoSymbol"}])

    def test_the_removals_are_sorted_and_hold_nothing_the_practice_needs(self):
        defaults = [{"key": "ctrl+s", "command": "workbench.action.files.save"},
                    {"key": "f1", "command": "workbench.action.showCommands"},
                    {"key": "left", "command": "cursorLeft"},
                    {"key": "ctrl+p", "command": "workbench.action.quickOpen"}]
        answered = self.ran(f"console.log(JSON.stringify(allowed.removals({json.dumps(defaults)})))")
        self.assertEqual(answered, [{"key": "ctrl+p", "command": "-workbench.action.quickOpen"},
                                    {"key": "f1", "command": "-workbench.action.showCommands"}])

    def test_the_default_document_is_read_as_the_workbench_writes_it(self):
        # The workbench's own document is JSON with `//` lines, so a plain
        # JSON.parse of it raises and the derivation would be empty — which
        # reads as "nothing to confine".
        text = '// Override key bindings by placing them into your key bindings file.\\n' \
               '[\\n{ "key": "ctrl+p", "command": "workbench.action.quickOpen" }\\n]'
        answered = self.ran(f"console.log(JSON.stringify(allowed.parse('{text}')))")
        self.assertEqual(answered, [{"key": "ctrl+p", "command": "workbench.action.quickOpen"}])

    def test_a_document_that_is_not_a_list_raises_rather_than_deriving_nothing(self):
        node = node_or_skip(self)
        done = subprocess.run([node, "-e", f"require('{SOURCE / 'allowed.js'}').parse('{{}}')"],
                              capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(done.returncode, 1)
        self.assertIn("not a list", done.stderr)


class TheSeed(unittest.TestCase):
    """The generated file the image bakes in, checked against the allow-list that made it."""

    def setUp(self):
        self.entries = json.loads(SEED.read_text(encoding="utf-8"))

    def test_it_is_a_list_of_removals_and_every_one_of_them_is_a_removal(self):
        self.assertTrue(self.entries)
        for entry in self.entries:
            self.assertEqual(sorted(entry), ["command", "key"])
            self.assertTrue(entry["command"].startswith("-"), entry)

    def test_every_command_it_removes_is_one_the_allow_list_refuses(self):
        node = node_or_skip(self)
        commands = sorted({entry["command"][1:] for entry in self.entries})
        done = subprocess.run(
            [node, "-e", f"const a = require('{SOURCE / 'allowed.js'}');"
                         f"console.log(JSON.stringify({json.dumps(commands)}.filter(a.allows)))"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), [],
                         "the seed removes a keybinding the allow-list permits; regenerate it")

    def test_it_takes_away_every_one_of_the_seven_that_has_a_keybinding_at_all(self):
        removed = {entry["command"][1:] for entry in self.entries}
        # ⚠️ `Run Task` has NO default keybinding: it is reachable only THROUGH
        # the palette, so closing the palette closes it and there is nothing
        # here to remove. That is stated rather than silently expected.
        self.assertNotIn("workbench.action.tasks.runTask", removed)
        for command in [name for name in THE_SEVEN if name != "workbench.action.tasks.runTask"]:
            with self.subTest(command=command):
                self.assertIn(command, removed)
        self.assertIn("workbench.action.openSettings", removed)

    def test_it_is_sorted_and_deduplicated_so_a_regeneration_is_an_empty_diff(self):
        marks = [(entry["key"], entry["command"]) for entry in self.entries]
        self.assertEqual(marks, sorted(marks))
        self.assertEqual(len(marks), len(set(marks)))

    def test_nothing_it_removes_is_a_key_the_practice_still_needs(self):
        kept = {entry["key"] for entry in self.entries if entry["command"] == "-workbench.action.files.save"}
        self.assertEqual(kept, set(), "the seed took Ctrl+S away from the reader")


class TheImageSeedsItBeforeAnySessionExists(unittest.TestCase):
    """⛔ The load-bearing measurement: a keybindings file written mid-session does nothing."""

    def test_the_dockerfile_bakes_the_generated_seed_in(self):
        self.assertIn("COPY docker/editor/seed/keybindings.json /opt/code-server/seed/keybindings.json",
                      DOCKERFILE)
        self.assertIn("/opt/code-server/seed/keybindings.json", DOCKERFILE.split("chmod 644", 1)[1])

    def test_the_entrypoint_writes_it_on_every_start_rather_than_only_the_first(self):
        # ⛔ The opposite rule from settings.json, deliberately: settings are
        # the READER's file and an overwrite would lose their edits; the
        # keybindings are the lockdown's, a reader confined by them has no
        # command with which to write one, and a volume from an earlier image
        # carrying an older copy is a keybinding that still fires.
        body = ENTRYPOINT.split("keys=", 1)[1]
        self.assertIn('cp "$SEED_KEYBINDINGS"', body)
        self.assertNotIn('if [ -e "$keys" ]', body)
        self.assertIn('mv "$keys.seed-partial" "$keys"', body,
                      "a container killed mid-copy must not leave half a keybindings file")

    def test_the_entrypoint_says_so_when_the_image_carries_no_seed(self):
        self.assertIn("no keybindings seed in this image", ENTRYPOINT)


class TheNameTheTwoLanguagesShare(unittest.TestCase):
    """The extension writes the derived file and the gate reads it, from two languages."""

    def test_the_javascript_and_the_python_spell_the_same_file(self):
        found = (SOURCE / "keybindings.js").read_text(encoding="utf-8")
        self.assertIn(f"const DERIVED = '{lockdown.DERIVED_KEYBINDINGS}';", found)

    def test_the_gate_reads_the_file_the_extension_writes(self):
        found = (EDITOR / "confinement.py").read_text(encoding="utf-8")
        self.assertIn("lockdown_extension.DERIVED_KEYBINDINGS", found)


class TheExtensionUnderNode(unittest.TestCase):
    """The tab guard and the keybinding report, run under `node` against the stub `vscode`."""

    def setUp(self):
        self.node = node_or_skip(self)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for path in lockdown.sources(SOURCE):
            shutil.copy(path, Path(self.tmp) / path.name)
        stub = Path(self.tmp) / "node_modules" / "vscode"
        stub.mkdir(parents=True)
        (stub / "package.json").write_text(
            json.dumps({"name": "vscode", "version": "1.0.0", "main": "index.js"}), encoding="utf-8")
        (stub / "index.js").write_text(test_lockdown.VSCODE_STUB, encoding="utf-8")
        (Path(self.tmp) / "harness.js").write_text(test_lockdown.HARNESS, encoding="utf-8")

    def ran(self, **env) -> dict:
        done = subprocess.run([self.node, str(Path(self.tmp) / "harness.js")], capture_output=True, text=True,
                              cwd=self.tmp, env={**os.environ, **env}, stdin=subprocess.DEVNULL)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def user_keybindings(self, entries) -> None:
        target = Path(self.tmp) / "user" / lockdown.DERIVED_KEYBINDINGS
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(entries), encoding="utf-8")

    PRACTICE = "file:///repo/sources/practice.txt"

    def tabs(self, *labels) -> str:
        held = [{"label": "practice.txt", "uri": self.PRACTICE}]
        held += [{"label": label, "uri": None} for label in labels]
        return json.dumps(held)

    def test_a_tab_that_is_not_the_file_this_window_opened_is_closed(self):
        read = self.ran(HARNESS_ACTIVE=json.dumps(self.PRACTICE), HARNESS_TABS=self.tabs("Settings"))
        self.assertEqual(read["closed"], ["Settings"])
        self.assertEqual(read["left"], ["practice.txt"])

    def test_it_closes_a_stray_whatever_opened_it_and_names_none_of_them(self):
        read = self.ran(HARNESS_ACTIVE=json.dumps(self.PRACTICE),
                        HARNESS_TABS=self.tabs("Settings", "Keyboard Shortcuts", "Extension: Java"))
        self.assertEqual(sorted(read["closed"]), ["Extension: Java", "Keyboard Shortcuts", "Settings"])
        self.assertEqual(read["left"], ["practice.txt"])
        # ⛔ The allow-list is ONE file and the deny set is everything else, so
        # no surface is named in the source. A name here would be the
        # deny-list this row exists to avoid.
        source = (SOURCE / "extension.js").read_text(encoding="utf-8")
        for named in ("Keyboard Shortcuts", "openSettings", "quickOpen"):
            self.assertNotIn(named, source)

    def test_a_window_whose_active_editor_is_unknown_closes_nothing(self):
        # ⛔ A guard that does not know what to KEEP must not start closing, or
        # a slow startup ends with the practice shut and a stray left open.
        read = self.ran(HARNESS_TABS=self.tabs("Settings"))
        self.assertEqual(read["closed"], [])
        self.assertEqual(read["left"], ["practice.txt", "Settings"])

    def test_a_tab_this_build_will_not_close_does_not_stop_the_others(self):
        read = self.ran(HARNESS_ACTIVE=json.dumps(self.PRACTICE),
                        HARNESS_TABS=self.tabs("Settings", "Keyboard Shortcuts"),
                        HARNESS_UNCLOSABLE="Settings")
        self.assertEqual(read["closed"], ["Keyboard Shortcuts"])

    def test_it_derives_the_removals_from_the_workbench_and_writes_them_for_the_gate(self):
        defaults = json.dumps([{"key": "ctrl+p", "command": "workbench.action.quickOpen"},
                               {"key": "ctrl+s", "command": "workbench.action.files.save"}])
        read = self.ran(HARNESS_ACTIVE=json.dumps(self.PRACTICE), HARNESS_TABS=self.tabs(),
                        HARNESS_DEFAULTS=f"// Default Keybindings\n{defaults}")
        self.assertEqual(read["opened"], "vscode://defaultsettings/keybindings.json")
        self.assertEqual(read["derived"], [{"key": "ctrl+p", "command": "-workbench.action.quickOpen"}])

    def test_it_reports_a_session_that_loaded_the_removals_as_nothing_missing(self):
        self.user_keybindings([{"key": "ctrl+p", "command": "-workbench.action.quickOpen"}])
        defaults = json.dumps([{"key": "ctrl+p", "command": "workbench.action.quickOpen"}])
        read = self.ran(HARNESS_ACTIVE=json.dumps(self.PRACTICE), HARNESS_TABS=self.tabs(),
                        HARNESS_DEFAULTS=f"// x\n{defaults}")
        self.assertIn("missing=0 extra=0 file=present", read["recorded"])
        self.assertIn("derived=1 loaded=1", read["recorded"])

    def test_a_regeneration_keeps_what_another_session_found_and_drops_what_is_now_allowed(self):
        # ⛔ Measured and load-bearing: the workbench's default list is not the
        # same in two sessions of one image, so a seed written by REPLACING
        # would oscillate. The union is monotonic, except for a command the
        # allow-list has since been widened to permit, which drops out.
        self.user_keybindings([{"key": "ctrl+shift+u", "command": "-workbench.action.output.toggleOutput"},
                               {"key": "ctrl+s", "command": "-workbench.action.files.save"}])
        defaults = json.dumps([{"key": "ctrl+p", "command": "workbench.action.quickOpen"}])
        read = self.ran(HARNESS_ACTIVE=json.dumps(self.PRACTICE), HARNESS_TABS=self.tabs(),
                        HARNESS_DEFAULTS=f"// x\n{defaults}")
        self.assertEqual(read["derived"],
                         [{"key": "ctrl+p", "command": "-workbench.action.quickOpen"},
                          {"key": "ctrl+shift+u", "command": "-workbench.action.output.toggleOutput"}])
        self.assertIn("extra=1", read["recorded"])

    def test_a_workbench_that_gained_a_command_is_reported_as_missing(self):
        # ⭐ THE instrument that says so. The seed was generated against one
        # workbench; a later one binds a key to a command the allow-list does
        # not permit; the derivation moves and the seed does not.
        self.user_keybindings([{"key": "ctrl+p", "command": "-workbench.action.quickOpen"}])
        defaults = json.dumps([{"key": "ctrl+p", "command": "workbench.action.quickOpen"},
                               {"key": "ctrl+alt+n", "command": "workbench.action.theNewThing"}])
        read = self.ran(HARNESS_ACTIVE=json.dumps(self.PRACTICE), HARNESS_TABS=self.tabs(),
                        HARNESS_DEFAULTS=f"// x\n{defaults}")
        self.assertIn("missing=1", read["recorded"])

    def test_a_session_with_no_keybindings_file_at_all_is_reported_as_absent(self):
        defaults = json.dumps([{"key": "ctrl+p", "command": "workbench.action.quickOpen"}])
        read = self.ran(HARNESS_ACTIVE=json.dumps(self.PRACTICE), HARNESS_TABS=self.tabs(),
                        HARNESS_DEFAULTS=f"// x\n{defaults}")
        self.assertIn("missing=1", read["recorded"])
        self.assertIn("file=absent", read["recorded"])

    def test_a_workbench_that_will_not_hand_over_its_defaults_says_so_rather_than_nothing(self):
        # ⚠️ An empty derivation and an unreadable one look the same in a
        # count, and the first reads as "there was nothing to confine".
        read = self.ran(HARNESS_ACTIVE=json.dumps(self.PRACTICE), HARNESS_TABS=self.tabs(),
                        HARNESS_NO_DEFAULTS="1")
        self.assertIn("could not be read", read["recorded"])
        self.assertNotIn("missing=0", read["recorded"])

    def test_the_window_is_still_confined_when_none_of_this_can_be_written(self):
        # ⭐ The report is evidence, never a precondition: the keybindings were
        # seeded by the image before this window existed.
        read = self.ran(HARNESS_NO_LOG_DIR="1", HARNESS_ACTIVE=json.dumps(self.PRACTICE),
                        HARNESS_TABS=self.tabs("Settings"))
        self.assertEqual(read["startup"], test_lockdown.CONFINE)
        self.assertEqual(read["closed"], ["Settings"])


class TheGatesOwnReading(unittest.TestCase):
    """`confinement.Confinement` — what it calls passing, with no Docker at all."""

    def confined(self, **changes) -> confinement.Confinement:
        state = {"image": "editor:probe", "opened": {chord: [] for chord, _ in confinement.CONFINED},
                 "find": True, "edited": True,
                 "report": f"{LOCK.banner} keybindings: derived=852 loaded=852 missing=0 extra=0 file=present"}
        state.update(changes)
        return confinement.Confinement(**state)

    def test_a_session_where_nothing_opened_and_the_practice_still_works_passes(self):
        self.assertTrue(self.confined().ok)

    def test_one_chord_that_opened_something_refuses_and_the_refusal_names_it(self):
        proof = self.confined(opened={"ctrl+shift+p": ["the command palette / quick open"]})
        self.assertFalse(proof.ok)
        self.assertIn("ctrl+shift+p opened the command palette", proof.complaint())

    def test_a_confinement_that_broke_the_practice_refuses_too(self):
        # ⛔ Both directions, and this is the one a confinement is tempted to
        # skip: a workbench where nothing at all works passes every negative
        # clause.
        self.assertFalse(self.confined(edited=False).ok)
        self.assertIn("never reached the file on disk", self.confined(edited=False).complaint())
        self.assertFalse(self.confined(find=False).ok)
        self.assertIn("cannot tell a confined session from a dead one", self.confined(find=False).complaint())

    def test_a_stale_seed_refuses_although_every_chord_this_gate_presses_did_nothing(self):
        report = f"{LOCK.banner} keybindings: derived=853 loaded=852 missing=1 extra=0 file=present"
        proof = self.confined(report=report)
        self.assertEqual(proof.missing, 1)
        self.assertFalse(proof.ok)
        self.assertIn("no longer covers this workbench", proof.complaint())

    def test_a_session_that_reported_nothing_is_not_read_as_nothing_missing(self):
        proof = self.confined(report="")
        self.assertEqual(proof.missing, -1)
        self.assertFalse(proof.ok)
        self.assertIn("no report at all", proof.complaint())

    def test_a_seed_that_takes_something_the_allow_list_permits_refuses_too(self):
        # ⚠️ The other direction, and the one a confinement gate forgets: the
        # seed removing a keybinding the practice is allowed to use.
        report = f"{LOCK.banner} keybindings: derived=852 loaded=853 missing=0 extra=1 file=present"
        proof = self.confined(report=report)
        self.assertEqual(proof.extra, 1)
        self.assertFalse(proof.ok)
        self.assertIn("takes something away from the practice", proof.complaint())

    def test_the_seven_the_reader_named_are_all_in_what_this_gate_presses(self):
        pressed = {chord for chord, _ in confinement.CONFINED}
        for chord in ("ctrl+p", "ctrl+shift+p", "ctrl+shift+f", "ctrl+shift+alt+l",
                      "ctrl+shift+o", "f5", "ctrl+,"):
            with self.subTest(chord=chord):
                self.assertIn(chord, pressed)


class TheBrowserProtocol(unittest.TestCase):
    """`cdp.key_event` — the chord spellings, which are the gate's hands."""

    def test_a_modified_letter_carries_the_browser_code_and_the_protocol_modifiers(self):
        self.assertEqual(cdp.key_event("ctrl+shift+p"),
                         {"modifiers": 10, "code": "KeyP", "key": "P",
                          "windowsVirtualKeyCode": 80, "nativeVirtualKeyCode": 80})

    def test_a_function_key_a_punctuation_key_and_a_named_key_are_all_spelled(self):
        self.assertEqual(cdp.key_event("f5")["code"], "F5")
        self.assertEqual(cdp.key_event("ctrl+,")["code"], "Comma")
        self.assertEqual(cdp.key_event("ctrl+`")["code"], "Backquote")
        self.assertEqual(cdp.key_event("escape")["code"], "Escape")

    def test_a_key_this_client_cannot_spell_refuses_rather_than_pressing_something_else(self):
        # ⛔ A silently wrong keystroke is a gate that passes because it
        # pressed nothing the workbench recognises.
        with self.assertRaises(cdp.CdpError):
            cdp.key_event("ctrl+unknownkey")

    def test_every_chord_the_gate_presses_can_be_spelled(self):
        for chord, _ in confinement.CONFINED + ((confinement.ALLOWED_CHORD[0], ""), ("escape", ""), ("ctrl+end", "")):
            with self.subTest(chord=chord):
                self.assertIn("code", cdp.key_event(chord))


@unittest.skipUnless(os.environ.get("TC_DOCKER") == "1", "needs Docker and a browser; set TC_DOCKER=1")
class TheGateOnARealSession(unittest.TestCase):
    """⛔ The proof, and the plant: re-enable ONE command and the gate must refuse.

    ⚠️ It does NOT rebuild the editor image. The plant is a one-layer image on
    top of the tagged one whose only change is the seed the entrypoint writes
    — which is exactly "one command re-enabled" and costs seconds rather than
    the twenty minutes a rebuild costs. ⭐ The thing under test is the GATE,
    and the gate reads a running workbench either way.
    """

    #: The command put back. ⭐ The one in the reader's own screenshot.
    PLANTED = "workbench.action.showCommands"

    @classmethod
    def setUpClass(cls):
        cls.image = subprocess.run(
            [sys.executable, str(EDITOR / "build.py"), "--runtimes", "java,maven", "--print-tag"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip()
        present = subprocess.run(["docker", "image", "inspect", cls.image],
                                 stdin=subprocess.DEVNULL, capture_output=True)
        if present.returncode != 0:
            raise unittest.SkipTest(f"{cls.image} is not on this host; build it first")

    def planted(self) -> str:
        """The same image with one command's keybinding put back into the seed."""
        entries = [entry for entry in json.loads(SEED.read_text(encoding="utf-8"))
                   if entry["command"] != f"-{self.PLANTED}"]
        tag = "code-server-toolchain/editor:w433-planted"
        with tempfile.TemporaryDirectory(prefix="w433-plant-") as work:
            (Path(work) / "keybindings.json").write_text(json.dumps(entries, indent=1) + "\n", encoding="utf-8")
            (Path(work) / "Dockerfile").write_text(
                f"FROM {self.image}\nUSER root\n"
                "COPY keybindings.json /opt/code-server/seed/keybindings.json\n"
                "RUN chmod 644 /opt/code-server/seed/keybindings.json\nUSER 1000\n", encoding="utf-8")
            done = subprocess.run(["docker", "build", "-t", tag, work],
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        self.addCleanup(subprocess.run, ["docker", "image", "rm", "-f", tag],
                        stdin=subprocess.DEVNULL, capture_output=True)
        return tag

    def test_the_tagged_image_confines_the_frame_and_still_lets_the_practice_be_done(self):
        proof = confinement.prove(self.image)
        self.assertEqual(proof.reached, [], proof.complaint())
        self.assertTrue(proof.find, "the editor's own find widget no longer opens")
        self.assertTrue(proof.edited, "what was typed never reached the file on disk")
        self.assertEqual(proof.missing, 0, proof.report)
        self.assertTrue(proof.ok, proof.complaint())

    def test_one_command_put_back_is_refused_and_the_refusal_names_the_chord(self):
        proof = confinement.prove(self.planted())
        self.assertFalse(proof.ok)
        self.assertIn("ctrl+shift+p", proof.reached)
        self.assertIn("the command palette", proof.complaint())
        # ⭐ And the exhaustive half saw it too, independently: the seed no
        # longer carries the removals the allow-list derives for that command.
        # ⚠️ Counted rather than assumed to be one — `Show and Run Commands` is
        # bound to TWO chords, `Ctrl+Shift+P` and `F1`, and putting the command
        # back puts both of them back.
        both = sum(1 for entry in json.loads(SEED.read_text(encoding="utf-8"))
                   if entry["command"] == f"-{self.PLANTED}")
        self.assertEqual(proof.missing, both, proof.report)

    def test_a_regeneration_keeps_every_removal_the_seed_already_carries(self):
        # ⛔ The regeneration path is the documented one, so it is the one run
        # here: a seed nobody can reproduce is a hand-edited file with a
        # comment claiming otherwise. ⚠️ Asserted as a SUPERSET and not as
        # equality, and that is the measurement rather than a loosening: the
        # workbench's default keybinding document is not the same in two
        # sessions of one image, so equality would be flaky while monotonicity
        # is the property the union exists to have.
        regenerated = {(entry["key"], entry["command"]) for entry in confinement.derived(self.image)}
        for entry in json.loads(SEED.read_text(encoding="utf-8")):
            with self.subTest(key=entry["key"], command=entry["command"]):
                self.assertIn((entry["key"], entry["command"]), regenerated)


if __name__ == "__main__":
    unittest.main()
