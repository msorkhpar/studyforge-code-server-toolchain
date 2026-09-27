"""The editor shows no chat, agent or AI surface, on a fresh and on an existing user-data volume.

⛔ **The reading this module started from** (a defect report): inside a practice
workspace the editor showed a "Build with Agent" side bar with a chat input,
"AI responses may be inaccurate" and "Generate Agent Instructions". The chat
EXTENSION and the Copilot modules were already deleted; Code 1.137's workbench
carries a chat of its own. ⭐ The image now takes it out of the product
(`docker/editor/no_ai.js`, run by the Dockerfile), and this module reads that
the way a reader meets it:

- **what is on screen** after the lockdown has settled: no chat view, no
  auxiliary bar, and no visible element labelled chat, agent, Copilot or AI;
- **what the workbench's own command registry holds**, read by a fixture
  extension (`tests/fixtures/command-probe`) installed into a derived image:
  no AI command id at all;
- **what asking for the chat does**: the four ways in (the view, the panel's
  id, its toggle and Quick Chat) each answer "not found";
- **the AI switch's default** as the workbench hands it to an extension host:
  on. ⚠️ Nothing on screen tells it apart from the hidden entitlement in a
  practice frame, so this is the reading that sees the first edit.
- **every frame from before the workbench's first script until it settles**,
  on a first start in a fresh browser profile and on a reload, in a Java
  practice window (`workbench_frames.watch`): no chat view and no secondary
  side bar in ANY frame. ⚠️ Every reading above is taken once the lockdown
  has settled, and a Java frame painted the secondary side bar headed "Chat"
  for about a second and a half while its Java projects opened, which none of
  them could see.

It reads that on a FRESH volume and on an EXISTING one whose settings.json the
entrypoint leaves alone, and whose settings turn the workbench's AI switch
back OFF, which is the hardest existing case: a default alone would lose it.

The static half runs everywhere; its `node` tests skip when no `node` is on
PATH. ⚠️ The browser half is skipped unless `TC_DOCKER=1`: it builds the
image, starts containers and drives a headless browser, and a missing browser
FAILS it rather than skipping it. `TC_SCREENSHOTS=<dir>` saves each session's
screenshot there.

    TC_DOCKER=1 python3 -m unittest tests.test_editor_no_ai -v

⭐ **Positive control, planted on the tagged image:** the same image with the
four edits taken back out (one derived layer, so the plant is provably the only
difference) must show the chat view and register the AI commands, or this
module is blind. ⭐ And the same image with the secondary side bar's start
override taken back out (the Dockerfile step "THE SECONDARY SIDE BAR NEVER
OPENS") must paint the chat container in some frame.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docker" / "editor"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import activation  # noqa: E402
import cdp  # noqa: E402
import java_session  # noqa: E402
import probe  # noqa: E402
import workbench_frames  # noqa: E402

BUILD = ROOT / "docker" / "editor" / "build.py"
SET = "java,maven"
DOCKERFILE = (ROOT / "docker" / "editor" / "Dockerfile").read_text(encoding="utf-8")
NO_AI = ROOT / "docker" / "editor" / "no_ai.js"
ALLOWED = ROOT / "lockdown" / "allowed.js"
PROBE = ROOT / "tests" / "fixtures" / "command-probe"
PROBE_ID = "probe.command-probe"
VSCODE = "/usr/lib/code-server/lib/vscode"
BUNDLES = (f"{VSCODE}/out/vs/code/browser/workbench/workbench.js",
           f"{VSCODE}/out/vs/workbench/workbench.web.main.internal.js")
#: Where the contract mounts the user-data volume, and code-server's data directory inside it.
LOCAL = "/home/coder/.local"
DATA = f"{LOCAL}/share/code-server"

#: THIS module's reading of an AI command id, spelled here rather than imported,
#: so a word dropped from the product's list is caught rather than agreed with.
AI_ID = re.compile(r"chat|copilot|codex|agent|mcp|languagemodel|^lm\.|aiedits|aicustomization|aisearch|withai"
                   r"|voice|prompt|skill|instructions|toolset", re.I)
#: The server's own log channel, which says "agent" and is not AI.
NOT_AI = re.compile(r"remoteagent", re.I)
#: What the secondary side bar step inserts at the head of the layout's overrides.
AUX_HIDDEN = "this.applyAuxiliaryBarHiddenOverride(!0);"
#: The fixture's ways into the chat, as `extension.js` names them.
OPENERS = ("workbench.action.openQuickChat", "workbench.action.chat.toggle", "workbench.panel.chat",
           "workbench.action.chat.open")

#: What a bundle's four anchors look like, in the minified shape of Code 1.137.
BUNDLE_TEXT = (
    'var nl="chat.disableAIFeatures";'
    'x={[nl]:{type:"boolean",description:d(8009,null),default:!1,scope:4}};'
    "class E{withConfiguration(e){return this._forceHidden||this.c.getValue(nl)===!0?{...e,hidden:!0}:e}}"
    'class R{registerCommand(s,o){if(!s)throw new Error("invalid command");if(typeof s=="string")'
    '{if(!o)throw new Error("invalid command");return this.registerCommand({id:s,handler:o})}let{id:e}=s}}'
    "class M{addCommand(s){return this._commands.set(s.id,s),0}}"
)
ANCHORS = {
    "the AI switch default": "default:!1,scope:4",
    "the chat entitlement gate": "withConfiguration(e){return this._forceHidden||",
    "the command registry": 'return this.registerCommand({id:s,handler:o})}',
    "the command palette": "addCommand(s){return this._commands.set(",
}

#: The page probe: what AI surface is visibly on screen. ⚠️ `width > 2`, since a closed part keeps a sash.
SURFACE = r"""(() => {
  const vis = (el) => { const s = getComputedStyle(el), b = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && b.width > 2 && b.height > 2; };
  const aux = document.querySelector('.part.auxiliarybar');
  const chat = [...document.querySelectorAll(
    '.interactive-session, .interactive-input-part, .chat-input-container, .quick-chat')].some(vis);
  const text = document.body ? document.body.innerText : '';
  const words = ['Build with Agent', 'AI responses may be inaccurate', 'Generate Agent Instructions']
    .filter((w) => text.includes(w));
  const rx = /chat|agent|copilot|\bai\b|sparkle|codex/i, labels = new Set();
  for (const el of document.querySelectorAll('[aria-label],[title],.codicon')) {
    const said = [el.getAttribute('aria-label'), el.getAttribute('title'), el.className].filter(Boolean).join(' | ');
    if (rx.test(said) && vis(el)) { labels.add(said.slice(0, 120)); }
  }
  return {auxiliary: !!(aux && vis(aux)), chat, words, labels: [...labels]};
})()"""

#: Takes the four edits back out of a bundle, for the positive control. ⛔ It
#: fails unless each one was found, so a plant that restored nothing is not read as a pass.
PLANT_JS = r"""
const fs = require('fs');
for (const bundle of process.argv.slice(2)) {
  let text = fs.readFileSync(bundle, 'utf8');
  const key = text.match(/([\w$]+)="chat\.disableAIFeatures"/)[1].replace(/\$/g, '\\$');
  const steps = [
    [new RegExp(`(\\[${key}\\]:\\{type:"boolean",description:[\\w$]+\\(\\d+,null\\),default:)!0,`), '$1!1,'],
    [/return!0\|\|this\._forceHidden\|\|/, 'return this._forceHidden||'],
    [/if\(\/chat\|[^\n]*?return\{dispose\(\)\{\}\};/, ''],
    [/if\(\/chat\|[^\n]*?return\{dispose\(\)\{\}\};/, ''],
  ];
  for (const [anchor, back] of steps) {
    if (!anchor.test(text)) { console.error(`${bundle}: ${anchor} is not there to take out`); process.exit(1); }
    text = text.replace(anchor, back);
  }
  fs.writeFileSync(bundle, text);
}
"""


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, **kwargs)


def ai_ids(commands: list[str]) -> list[str]:
    return [c for c in commands if AI_ID.search(c) and not NOT_AI.search(c)]


def pack_probe(target: Path) -> None:
    """The fixture as a `.vsix`: the workbench installs a package, never a copied folder."""
    manifest = json.loads((PROBE / "package.json").read_text(encoding="utf-8"))
    identity = (f'<Identity Language="en-US" Id="{manifest["name"]}" Version="{manifest["version"]}" '
                f'Publisher="{manifest["publisher"]}"/>')
    with zipfile.ZipFile(target, "w") as packed:
        packed.writestr("[Content_Types].xml",
                        '<?xml version="1.0" encoding="utf-8"?><Types xmlns="http://schemas.openxmlformats.org/'
                        'package/2006/content-types"><Default Extension="json" ContentType="application/json"/>'
                        '<Default Extension="js" ContentType="application/javascript"/><Default '
                        'Extension="vsixmanifest" ContentType="text/xml"/></Types>')
        packed.writestr("extension.vsixmanifest",
                        '<?xml version="1.0" encoding="utf-8"?><PackageManifest Version="2.0.0" xmlns="http://'
                        f'schemas.microsoft.com/developer/vsx-schema/2011"><Metadata>{identity}<DisplayName>'
                        f'{manifest["displayName"]}</DisplayName><Description xml:space="preserve">fixture'
                        '</Description><Properties><Property Id="Microsoft.VisualStudio.Code.Engine" '
                        f'Value="{manifest["engines"]["vscode"]}"/></Properties></Metadata><Installation>'
                        '<InstallationTarget Id="Microsoft.VisualStudio.Code"/></Installation><Dependencies/>'
                        '<Assets><Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json"'
                        ' Addressable="true"/></Assets></PackageManifest>')
        for name in ("package.json", "extension.js"):
            packed.write(PROBE / name, f"extension/{name}")


class ThePatchIsInTheBuild(unittest.TestCase):
    """What a text and the script itself can establish, with no image."""

    def setUp(self):
        self.node = shutil.which("node")

    def _need_node(self):
        if not self.node:
            self.skipTest("no node on PATH; the image tests run the script in the build for real")

    def _patch(self, text: str) -> tuple[subprocess.CompletedProcess, str]:
        with tempfile.TemporaryDirectory(prefix="no-ai-") as scratch:
            bundle = Path(scratch) / "workbench.js"
            bundle.write_text(text, encoding="utf-8")
            done = run([self.node, str(NO_AI), str(bundle)])
            return done, bundle.read_text(encoding="utf-8")

    def test_the_dockerfile_runs_it_offline_on_both_bundles(self):
        step = DOCKERFILE[DOCKERFILE.index("THE WORKBENCH'S OWN CHAT IS TAKEN OUT"):]
        step = step[:step.index("\n\n")]
        self.assertIn("RUN --network=none --mount=type=bind,source=docker/editor/no_ai.js", step)
        for bundle in BUNDLES:
            self.assertIn(bundle, step)

    def test_each_edit_lands_once(self):
        self._need_node()
        done, text = self._patch(BUNDLE_TEXT)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('[nl]:{type:"boolean",description:d(8009,null),default:!0,scope:4}', text)
        self.assertIn("withConfiguration(e){return!0||this._forceHidden||", text)
        self.assertEqual(text.count(".test(s.id))return{dispose(){}};"), 2)

    def test_a_missing_or_doubled_anchor_fails_naming_the_edit_and_writes_nothing(self):
        self._need_node()
        for name, anchor in ANCHORS.items():
            for broken, how in ((BUNDLE_TEXT.replace(anchor, "gone"), "missing"),
                                (BUNDLE_TEXT + BUNDLE_TEXT.split(";", 1)[1], "doubled")):
                if how == "doubled" and name == "the AI switch default":
                    continue  # its key is declared once; doubling the whole text is the next case
                with self.subTest(edit=name, how=how):
                    done, text = self._patch(broken)
                    self.assertEqual(done.returncode, 1)
                    self.assertIn(name, done.stderr)
                    self.assertEqual(text, broken, "a refused bundle must be left as it was")

    def test_a_second_run_is_refused(self):
        self._need_node()
        done, once = self._patch(BUNDLE_TEXT)
        self.assertEqual(done.returncode, 0, done.stderr)
        again, _ = self._patch(once)
        self.assertEqual(again.returncode, 1)
        self.assertIn("already refuses the AI commands", again.stderr)

    def test_it_refuses_the_ai_commands_and_never_a_practice_command(self):
        # ⭐ Read through the very code the edit inserts, `refuse`, not through the pattern alone.
        self._need_node()
        ai = ["workbench.action.chat.open", "workbench.action.openQuickChat", "inlineChat.start",
              "workbench.panel.chat", "workbench.mcp.addConfiguration", "agentSession.archive",
              "workbench.action.chat.generateAgentInstructions", "_workbench.action.openCopilotSurvey",
              "lm.addLanguageModelsProviderGroup", "workbench.command.new.prompt", "search.action.searchWithAI",
              "workbench.action.terminal.startVoice", "aiCustomization.openManagementEditor"]
        kept = ["workbench.action.files.save", "editor.action.startFindReplaceAction", "cursorLeft",
                "workbench.action.output.show.remoteagent", "java.test.editor.run", "testing.reRunFailTests",
                "editor.action.trimTrailingWhitespace", "workbench.action.closeAuxiliaryBar"]
        script = (f"const n=require({json.dumps(str(NO_AI))}),a=require({json.dumps(str(ALLOWED))});"
                  "const f=new Function('c',n.refuse('c')+'return false;'),r=(id)=>f({id})!==false;"
                  f"console.log(JSON.stringify({{ai:{json.dumps(ai)}.filter(r),"
                  f"kept:{json.dumps(kept)}.concat(a.COMMANDS).filter(r)}}))")
        done = run([self.node, "-e", script])
        self.assertEqual(done.returncode, 0, done.stderr)
        read = json.loads(done.stdout)
        self.assertEqual(read["ai"], ai, "an AI command the product would still register")
        self.assertEqual(read["kept"], [], "a command a practice needs would be refused")


@unittest.skipUnless(os.environ.get("TC_DOCKER") == "1", "set TC_DOCKER=1 to build images and run containers")
class NoAiSurfaceInASession(unittest.TestCase):
    """The effect, in a real browser, on the tagged image and on its planted twin."""

    @classmethod
    def setUpClass(cls):
        cls.tag = run([sys.executable, str(BUILD), "--runtimes", SET, "--print-tag"]).stdout.strip()
        built = run([sys.executable, str(BUILD), "--runtimes", SET])
        if built.returncode != 0:
            raise AssertionError(f"the editor build did not pass its own gate:\n{built.stdout}\n{built.stderr}")
        cls.made: list[str] = []
        cls.volumes: list[str] = []
        try:
            cls.probed = cls._derive(cls.tag, "probed")
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        for volume in cls.volumes:
            run(["docker", "volume", "rm", "-f", volume])
        for image in reversed(cls.made):
            run(["docker", "image", "rm", "-f", image])
        if os.environ.get("TC_KEEP_IMAGES") != "1":
            run(["docker", "image", "rm", "-f", cls.tag])

    @classmethod
    def _derive(cls, base: str, what: str) -> str:
        """`base` plus one layer: the probe installed, or the four edits taken back out."""
        name = f"no-ai-{what}:{uuid.uuid4().hex[:12]}"
        with tempfile.TemporaryDirectory(prefix=f"no-ai-{what}-") as context:
            if what == "probed":
                pack_probe(Path(context) / "probe.vsix")
                step = ("COPY probe.vsix /tmp/probe.vsix\nRUN code-server --extensions-dir /opt/code-server/extensions "
                        "--install-extension /tmp/probe.vsix && rm -rf /tmp/probe.vsix /root/.local/share/code-server "
                        "&& chown -R 1000:1000 /opt/code-server/extensions")
            else:
                Path(context, "plant.js").write_text(PLANT_JS, encoding="utf-8")
                step = f"COPY plant.js /tmp/plant.js\nRUN {VSCODE}/../node /tmp/plant.js {' '.join(BUNDLES)}"
            Path(context, "Dockerfile").write_text(f"FROM {base}\nUSER root\n{step}\nUSER 1000\n", encoding="utf-8")
            done = run(["docker", "build", "--pull=false", "-t", name, context])
        if done.returncode != 0:
            raise AssertionError(f"the {what} layer did not build:\n{done.stderr}")
        cls.made.append(name)
        return name

    def _existing_volume(self) -> str:
        """A user-data volume that already carries a settings.json, one that turns the AI switch back off."""
        volume = f"no-ai-existing-{uuid.uuid4().hex[:12]}"
        self.volumes.append(volume)
        seed = "/opt/code-server/seed/settings.json"
        write = (f"mkdir -p {DATA}/User && sed 's|\"files.autoSave\": \"afterDelay\",|&\\n    "
                 f"\"chat.disableAIFeatures\": false,|' {seed} > {DATA}/User/settings.json "
                 f"&& grep -c 'chat.disableAIFeatures' {DATA}/User/settings.json")
        done = run(["docker", "run", "--rm", "--network", "none", "--user", "1000:1000", "-v", f"{volume}:{LOCAL}",
                    "--entrypoint", "sh", self.tag, "-c", write])
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "1"), done.stderr)
        return volume

    def _session(self, image: str, label: str, volume: str | None = None) -> dict:
        """Open one practice-shaped window in `image`, wait for the probe, and read the screen."""
        found = activation.browser()
        name = f"no-ai-probe-{uuid.uuid4().hex[:12]}"
        mounts = ["-v", f"{volume}:{LOCAL}"] if volume else []
        browser = None
        try:
            activation.seed(image, name, {probe.MAIN: probe.MAIN_TEXT})
            activation.start(image, name, name, *mounts)
            port = activation.published_port(name)
            activation.wait_for_health(port)
            debug = probe.free_port()
            browser = activation.Browser(found, "--window-size=1400,900", f"--remote-debugging-port={debug}",
                                         activation.workbench_url(port, name=probe.MAIN))
            page = cdp.wait_for_target(debug, f":{port}/")
            with cdp.Session(page["webSocketDebuggerUrl"]) as session:
                session.call("Runtime.enable")
                probe.wait_for_editor(session)
                seen = self._probe_report(name)
                time.sleep(3.0)  # let a chat the probe opened lay itself out
                seen["surface"] = cdp.evaluate(session, SURFACE)
                shot = session.call("Page.captureScreenshot", {"format": "png"}, timeout=60)
            keep = os.environ.get("TC_SCREENSHOTS")
            if keep:
                Path(keep).mkdir(parents=True, exist_ok=True)
                Path(keep, f"{label}.png").write_bytes(base64.b64decode(shot["data"]))
            seen["log"] = run(["docker", "logs", name]).stdout
            return seen
        finally:
            if browser is not None:
                browser.close()
            activation.remove(name, name)

    def _probe_report(self, name: str) -> dict:
        """The fixture's `commands.json`, from THIS session's log directory (a volume keeps older ones)."""
        read = f'cat "$(ls -td {DATA}/logs/*/ | head -1)"exthost*/{PROBE_ID}/commands.json 2>/dev/null'
        deadline = time.monotonic() + activation.ACTIVATION_TIMEOUT
        while time.monotonic() < deadline:
            out = run(["docker", "exec", name, "sh", "-c", read]).stdout
            if out.strip():
                return json.loads(out)
            time.sleep(activation.POLL)
        raise AssertionError("the command probe wrote nothing, so this session read nothing")

    def _assert_no_ai(self, seen: dict) -> None:
        self.assertIs(seen["aiSwitch"]["defaultValue"], True, f"the AI switch does not default on: {seen['aiSwitch']}")
        self.assertGreater(len(seen["commands"]), 1000, "too few commands to be the workbench's registry")
        self.assertEqual(ai_ids(seen["commands"]), [], "AI commands the workbench still registers")
        for opener in OPENERS:
            self.assertIn("not found", seen["opened"][opener], f"{opener} was not refused: {seen['opened']}")
        surface = seen["surface"]
        self.assertEqual((surface["auxiliary"], surface["chat"], surface["words"], surface["labels"]),
                         (False, False, [], []), f"an AI surface is on screen: {surface}")

    def test_a_fresh_volume_shows_no_ai_surface_and_registers_no_ai_command(self):
        self._assert_no_ai(self._session(self.probed, "fresh"))

    def test_an_existing_settings_file_that_turns_ai_back_on_shows_none_either(self):
        seen = self._session(self.probed, "existing", volume=self._existing_volume())
        self.assertIn("settings exist at", seen["log"], "the entrypoint wrote the seed, so the volume was not existing")
        self.assertIs(seen["aiSwitch"]["globalValue"], False, "the settings file did not turn the switch back off")
        self._assert_no_ai(seen)

    def _assert_no_chat_in_any_frame(self, logs: list[dict]) -> None:
        for start, seen in zip(("first start", "reload"), logs):
            with self.subTest(start=start):
                self.assertGreater(seen["frames"], 100, f"too few frames were watched to say anything: {seen}")
                self.assertEqual((seen["chat"], seen["auxiliary"]), (0, 0),
                                 f"a chat view or the secondary side bar was painted: {seen}")

    def test_no_frame_of_a_fresh_start_or_a_reload_paints_a_chat(self):
        self._assert_no_chat_in_any_frame(workbench_frames.watch(self.tag, "no-ai-frames"))

    def test_no_frame_on_an_existing_settings_file_that_turns_ai_back_on_paints_a_chat_either(self):
        volume = self._existing_volume()
        self._assert_no_chat_in_any_frame(workbench_frames.watch(self.tag, "no-ai-frames", "-v", f"{volume}:{LOCAL}"))

    def test_the_start_override_planted_back_out_paints_the_chat_container(self):
        undo = " && ".join(f"grep -qF '{AUX_HIDDEN}' {b} && sed -i 's/{AUX_HIDDEN}//' {b}" for b in BUNDLES)
        planted = java_session.derived(self.tag, "no-ai-aux-plant", f"RUN {undo}")
        self.made.append(planted)
        first, _ = workbench_frames.watch(planted, "no-ai-aux-plant")
        self.assertGreater(first["chat"], 0, f"the plant painted no chat container, so this module is blind: {first}")
        self.assertIn("workbench.panel.chat", first["seen"], first)

    def test_the_edits_planted_back_out_show_the_chat_again(self):
        planted = self._derive(self._derive(self.tag, "planted"), "probed")
        seen = self._session(planted, "planted")
        self.assertGreater(len(ai_ids(seen["commands"])), 100, "the plant registered no AI command: this is blind")
        self.assertEqual(seen["opened"]["workbench.action.chat.open"], "ran", seen["opened"])
        surface = seen["surface"]
        # ⚠️ The view's welcome depends on the mode it opened in: "Build with Agent"
        # in agent mode, "Ask about your code" in ask mode; both say the next two.
        self.assertTrue(surface["auxiliary"] and surface["chat"]
                        and {"AI responses may be inaccurate", "Generate Agent Instructions"} <= set(surface["words"]),
                        f"the plant showed no chat view, so this module is blind: {surface}")


if __name__ == "__main__":
    unittest.main()
