"""The editor carries no Copilot CLI, and no session forks an agent host (W454).

⛔ **The reading this row started from** (`W449/1`, ruled on 2026-09-23): the
chat extension was deleted, and the SERVER half stayed. The first workbench to
connect made the server fork `bootstrap-fork --type=agentHost`, and that
process started the bundled Copilot CLI,
`node_modules/@github/copilot-linux-x64/index.js --headless`, on a container
with egress. ⭐ The image now deletes the modules and switches the fork off in
the server and in the workbench (`docker/editor/Dockerfile`, the W454 step).
This module reads it the way it matters: `ps` inside a started editor while a
real browser holds a real session.

The static half runs everywhere. ⚠️ The Docker half is skipped unless
`TC_DOCKER=1`: it builds the image, starts containers and drives a headless
browser, and a missing browser FAILS it rather than skipping it.

    TC_DOCKER=1 TC_KEEP_IMAGES=1 python3 -m unittest tests.test_editor_agent_host -v

⭐ **Positive controls.** The same image with the two switches planted back
out (one derived layer, so the plant is provably the only difference) must show
the agent host forked, or the `ps` reading is blind. A build that keeps the
modules must be refused.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "docker" / "editor"))

import activation  # noqa: E402
import build_inputs  # noqa: E402
import cdp  # noqa: E402
import confinement  # noqa: E402
import editor_plan  # noqa: E402

BUILD = ROOT / "docker" / "editor" / "build.py"
SET = "java,maven"
DOCKERFILE = (ROOT / editor_plan.DOCKERFILE).read_text(encoding="utf-8")
WORK = ROOT / ".work" / "tests-agent-host"

VSCODE = "/usr/lib/code-server/lib/vscode"
SERVER = f"{VSCODE}/out/server-main.js"
BUNDLES = (
    f"{VSCODE}/out/vs/code/browser/workbench/workbench.js",
    f"{VSCODE}/out/vs/workbench/workbench.web.main.internal.js",
)
#: The module loop, exactly as the step spells it, so a plant can empty it.
DELETION = "for gone in @github/copilot @github/copilot-linux-x64 @github/copilot-linux-arm64 @github/copilot-sdk"
#: What the server logs when it takes upstream's own "no agent host" path.
UNAVAILABLE = "Registered unavailable IPC channel 'agentHostProxy'"
#: What the workbench logs when it tries to reach an agent host.
CONNECTING = "Connecting to remote agent host"
#: How long a session is watched after the workbench first paints. ⚠️ The
#: upstream fork came at about 2 s; the workbench's backoff retries at 1, 2, 4,
#: 8 and 16 s, so 30 s covers every one of those.
WATCH = 30.0

#: Runs in the workbench's document BEFORE any of its own script, and keeps
#: every console line, so the reader-facing console can be read back.
CONSOLE = r"""
(function () {
  var out = window.__console = [];
  ['log', 'info', 'warn', 'error', 'debug'].forEach(function (level) {
    var original = console[level];
    console[level] = function () {
      try { out.push(level + ': ' + Array.prototype.map.call(arguments, String).join(' ')); } catch (e) {}
      return original.apply(this, arguments);
    };
  });
})();
"""


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, **kwargs)


class TheStepIsInTheBuild(unittest.TestCase):
    """What a text can establish: every module goes, both switches are guarded."""

    def test_every_copilot_module_is_deleted_and_the_build_fails_if_one_is_left(self):
        self.assertIn(DELETION, DOCKERFILE)
        self.assertIn("-maxdepth 2 -iname '*copilot*'", DOCKERFILE)
        self.assertIn("the Copilot CLI is still in the product", DOCKERFILE)

    def test_the_server_takes_the_no_agent_host_branch_and_refuses_a_miss(self):
        self.assertIn(SERVER.replace(VSCODE, "$vscode"), DOCKERFILE)
        self.assertIn("W454 patches exactly one", DOCKERFILE)
        self.assertIn("the agent host was not switched off", DOCKERFILE)

    def test_both_workbench_bundles_are_disabled_and_a_miss_is_refused(self):
        for bundle in BUNDLES:
            self.assertIn(bundle.replace(VSCODE, "$vscode"), DOCKERFILE)
        self.assertIn("the agent host enablement was not switched off", DOCKERFILE)


@unittest.skipUnless(os.environ.get("TC_DOCKER") == "1", "set TC_DOCKER=1 to build images and run containers")
class NoSessionForksAnAgentHost(unittest.TestCase):
    """The effect, with `ps`, on the tagged image and on its planted twin."""

    @classmethod
    def setUpClass(cls):
        cls.tag = run([sys.executable, str(BUILD), "--runtimes", SET, "--print-tag"]).stdout.strip()
        built = run([sys.executable, str(BUILD), "--runtimes", SET])
        if built.returncode != 0:
            raise AssertionError(f"the editor build did not pass its own gate:\n{built.stdout}\n{built.stderr}")
        cls.planted: list[str] = []

    @classmethod
    def tearDownClass(cls):
        for image in cls.planted:
            run(["docker", "image", "rm", "-f", image])
        if os.environ.get("TC_KEEP_IMAGES") != "1":
            run(["docker", "image", "rm", "-f", cls.tag])

    def _switched_back_on(self) -> str:
        """The tagged image with both switches undone, as one derived layer."""
        name = f"agent-host-plant:{uuid.uuid4().hex[:12]}"
        undo = "; ".join([f"sed -i 's/else if(!0||/else if(/' {SERVER}"]
                         + [f"sed -i 's/super(!1\\&\\&!!/super(!!/' {b}" for b in BUNDLES])
        with tempfile.TemporaryDirectory(prefix="agent-host-plant-") as context:
            Path(context, "Dockerfile").write_text(
                f"FROM {self.tag}\nUSER root\nRUN {undo}\nUSER 1000\n", encoding="utf-8")
            done = run(["docker", "build", "-t", name, context])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.planted.append(name)
        return name

    def _session(self, image: str) -> dict:
        """Open one practice-shaped window in `image`, and sample `ps` inside it while it runs."""
        found = activation.browser()
        name = f"agent-host-probe-{uuid.uuid4().hex[:12]}"
        seen = {"forks": set(), "agent": [], "console": [], "log": ""}
        with tempfile.TemporaryDirectory(prefix="agent-host-probe-") as scratch:
            sources = Path(scratch) / "sources"
            sources.mkdir()
            (sources / confinement.MAIN).write_text(confinement.MAIN_TEXT, encoding="utf-8")
            Path(scratch).chmod(0o755)
            debug = confinement.free_port()
            browser = None
            try:
                activation.start(image, name, sources)
                port = activation.published_port(name)
                activation.wait_for_health(port)
                browser = subprocess.Popen(
                    [found, *activation.BROWSER_FLAGS, f"--remote-debugging-port={debug}",
                     f"--user-data-dir={Path(scratch) / 'profile'}", "about:blank"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                page = cdp.wait_for_target(debug, "about:blank")
                with cdp.Session(page["webSocketDebuggerUrl"]) as session:
                    session.call("Page.enable")
                    session.call("Runtime.enable")
                    session.call("Page.addScriptToEvaluateOnNewDocument", {"source": CONSOLE})
                    session.call("Page.navigate", {"url": activation.workbench_url(port, name=confinement.MAIN)})
                    deadline = time.monotonic() + WATCH + activation.HEALTH_TIMEOUT
                    watched = None
                    while watched is None or time.monotonic() < watched + WATCH:
                        self.assertLess(time.monotonic(), deadline, "the workbench never painted")
                        if watched is None and cdp.evaluate(session, "!!document.querySelector('.monaco-workbench')"):
                            watched = time.monotonic()
                        listing = run(["docker", "exec", name, "ps", "-eo", "args", "--width", "400"]).stdout
                        for line in listing.splitlines():
                            if "--type=" in line:
                                seen["forks"].add(line.split("--type=", 1)[1].split()[0])
                            if "agentHost" in line or "copilot" in line:
                                seen["agent"].append(line)
                        time.sleep(1)
                    seen["console"] = list(cdp.evaluate(session, "window.__console") or [])
                logs = run(["docker", "logs", name])
                seen["log"] = logs.stdout + logs.stderr
            finally:
                if browser is not None:
                    browser.terminate()
                    browser.wait(timeout=20)
                run(["docker", "rm", "-f", name])
        return seen

    def test_the_tagged_image_carries_no_copilot_module(self):
        listing = run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "sh", self.tag, "-c",
                       f"ls {VSCODE}/node_modules; echo ---; find {VSCODE}/node_modules -maxdepth 2 -iname '*copilot*'"])
        shipped, _, left = listing.stdout.partition("---")
        # ⭐ The POSITIVE CONTROL: a path that moved in a later code-server would
        # list nothing, and "nothing called copilot" would then prove nothing.
        self.assertGreater(len(shipped.split()), 10, f"{VSCODE}/node_modules lists nothing, so this is blind")
        self.assertEqual(left.split(), [])

    def test_a_session_on_the_tagged_image_forks_no_agent_host_and_runs_no_copilot(self):
        seen = self._session(self.tag)
        # ⭐ The instrument sees forks at all: the extension host is one.
        self.assertIn("extensionHost", seen["forks"], f"ps saw no extension host, so it is blind: {seen['forks']}")
        self.assertNotIn("agentHost", seen["forks"])
        self.assertEqual(seen["agent"], [])
        self.assertIn(UNAVAILABLE, seen["log"])
        self.assertEqual([line for line in seen["console"] if CONNECTING in line], [])

    def test_the_switches_planted_back_out_fork_the_agent_host_again(self):
        seen = self._session(self._switched_back_on())
        self.assertIn("agentHost", seen["forks"], f"the plant forked no agent host, so this module is blind: {seen}")
        self.assertTrue([line for line in seen["console"] if CONNECTING in line], seen["console"])

    def test_a_build_that_keeps_the_copilot_cli_is_refused(self):
        root = build_inputs.copy_inputs(WORK / "keeps-the-cli")
        try:
            path = root / editor_plan.DOCKERFILE
            text = path.read_text(encoding="utf-8")
            self.assertEqual(text.count(DELETION), 1)
            path.write_text(text.replace(DELETION, "for gone in nothing-by-this-name"), encoding="utf-8")
            planted = run([sys.executable, str(BUILD), "--root", str(root), "--runtimes", SET, "--print-tag"])
            built = run([sys.executable, str(BUILD), "--root", str(root), "--runtimes", SET])
            if built.returncode == 0:
                # ⚠️ Only a plant that wrongly built leaves a tag, and only then is one removed.
                self.planted.append(planted.stdout.strip())
            self.assertNotEqual(built.returncode, 0, "the planted build succeeded")
            self.assertIn("the Copilot CLI is still in the product", built.stdout + built.stderr)
        finally:
            subprocess.run(["rm", "-rf", str(WORK)], check=False)


if __name__ == "__main__":
    unittest.main()
