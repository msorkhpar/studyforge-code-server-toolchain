"""The practice frame never paints the Explorer — measured from the first frame.

⛔ **The defect this row started from** (reported 2026-09-23): the Explorer side
bar of the code-server frame stayed open until the page had fully loaded, and
only then closed. ⚠️ Measured on code-server 4.137.0 in a real browser: every
frame painted the primary side bar from the workbench's first frame for up to
seven seconds, until the lockdown's `closeSidebar` passes won. ⭐ The image now
starts the side bar CLOSED (`docker/editor/Dockerfile`, the side bar step), and this
module reads that the way a reader sees it: every animation frame, from before
the workbench's own first script, never a single end state.

The static half runs everywhere. ⚠️ The browser half is skipped unless
`TC_DOCKER=1`: it builds the image, starts containers and drives a headless
browser, and a missing browser FAILS it rather than skipping it.

    TC_DOCKER=1 python3 -m unittest tests.test_editor_layout -v

⭐ **Positive control, planted on the tagged image:** the same image with the
upstream default put back into its bundle (one derived layer, so the plant is
provably the only difference) must show the Explorer painted, or this module is
blind.
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
sys.path.insert(0, str(ROOT / "docker" / "editor"))

import activation  # noqa: E402
import cdp  # noqa: E402
import confinement  # noqa: E402
import editor_plan  # noqa: E402

BUILD = ROOT / "docker" / "editor" / "build.py"
SET = "java,maven"
DOCKERFILE = (ROOT / editor_plan.DOCKERFILE).read_text(encoding="utf-8")

#: The two workbench bundles that carry the side bar's default, and what it is set to.
BUNDLES = (
    "/usr/lib/code-server/lib/vscode/out/vs/code/browser/workbench/workbench.js",
    "/usr/lib/code-server/lib/vscode/out/vs/workbench/workbench.web.main.internal.js",
)
HIDDEN = "SIDEBAR_HIDDEN.defaultValue=!0,"

#: How long a session is watched after the workbench first paints. ⚠️ Longer
#: than the lockdown's last retry (12 s), which is the latest a close — and so a
#: side bar that had been open — could land.
WATCH = 20.0

#: Runs in the workbench's document BEFORE any of its own script, and records
#: every animation frame in which the primary side bar is laid out and visible.
#: ⭐ Per frame, because the defect is a FLASH: an end state reads closed.
PAINTED = r"""
(function () {
  var log = window.__sidebar = { frames: 0, painted: 0, workbench: false };
  function tick() {
    log.frames += 1;
    if (document.querySelector('.monaco-workbench')) { log.workbench = true; }
    var bar = document.querySelector('.part.sidebar');
    if (bar) {
      var box = bar.getBoundingClientRect(), style = getComputedStyle(bar);
      if (box.width > 2 && box.height > 2 && style.display !== 'none' && style.visibility !== 'hidden') {
        log.painted += 1;
      }
    }
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
})();
"""


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, **kwargs)


class TheStepIsInTheBuild(unittest.TestCase):
    """What a text can establish: both bundles are patched, and the step refuses a miss."""

    def test_both_bundles_are_patched_to_the_hidden_default(self):
        for bundle in BUNDLES:
            self.assertIn(bundle, DOCKERFILE)
        self.assertIn("s/SIDEBAR_HIDDEN\\.defaultValue=[^,]*,/SIDEBAR_HIDDEN.defaultValue=!0,/", DOCKERFILE)

    def test_the_step_fails_the_build_unless_exactly_one_default_was_found_and_replaced(self):
        self.assertIn('[ "$found" = 1 ]', DOCKERFILE)
        self.assertIn("side bar defaults; this step patches exactly one", DOCKERFILE)
        self.assertIn("the side bar default was not replaced", DOCKERFILE)


@unittest.skipUnless(os.environ.get("TC_DOCKER") == "1", "set TC_DOCKER=1 to build images and run containers")
class TheSideBarIsNeverPainted(unittest.TestCase):
    """The effect, in a real browser, on the tagged image and on its planted twin."""

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

    def _upstream(self) -> str:
        """The tagged image with the upstream default put back, as one derived layer."""
        name = f"layout-plant:{uuid.uuid4().hex[:12]}"
        undo = "; ".join(f"sed -i 's/{HIDDEN}/SIDEBAR_HIDDEN.defaultValue=!1,/' {b}" for b in BUNDLES)
        with tempfile.TemporaryDirectory(prefix="layout-plant-") as context:
            Path(context, "Dockerfile").write_text(
                f"FROM {self.tag}\nUSER root\nRUN {undo}\nUSER 1000\n", encoding="utf-8")
            done = run(["docker", "build", "-t", name, context])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.planted.append(name)
        return name

    def _watch(self, image: str) -> dict:
        """Open one practice-shaped window in `image` and count the frames that painted the side bar.

        ⚠️ Its own container and browser rather than `confinement.session`,
        because the counter must be installed BEFORE the workbench's first
        script, and that session's browser is already at the workbench.
        """
        found = activation.browser()
        name = f"layout-probe-{uuid.uuid4().hex[:12]}"
        debug = confinement.free_port()
        browser = None
        try:
            activation.seed(image, name, {confinement.MAIN: confinement.MAIN_TEXT})
            activation.start(image, name, name)
            port = activation.published_port(name)
            activation.wait_for_health(port)
            browser = activation.Browser(found, f"--remote-debugging-port={debug}", "about:blank")
            page = cdp.wait_for_target(debug, "about:blank")
            with cdp.Session(page["webSocketDebuggerUrl"]) as session:
                session.call("Page.enable")
                session.call("Runtime.enable")
                session.call("Page.addScriptToEvaluateOnNewDocument", {"source": PAINTED})
                session.call("Page.navigate", {"url": activation.workbench_url(port, name=confinement.MAIN)})
                deadline = time.monotonic() + activation.HEALTH_TIMEOUT
                while not cdp.evaluate(session, "!!(window.__sidebar && window.__sidebar.workbench)"):
                    self.assertLess(time.monotonic(), deadline, "the workbench never painted")
                    time.sleep(0.25)
                time.sleep(WATCH)
                return dict(cdp.evaluate(session, "window.__sidebar"))
        finally:
            if browser is not None:
                browser.close()
            activation.remove(name, name)

    def test_the_tagged_image_paints_no_side_bar_from_its_first_frame(self):
        seen = self._watch(self.tag)
        self.assertGreater(seen["frames"], 100, f"too few frames were watched to say anything: {seen}")
        self.assertEqual(seen["painted"], 0, f"the side bar was painted in {seen['painted']} frames")

    def test_the_upstream_default_planted_back_paints_the_explorer(self):
        seen = self._watch(self._upstream())
        self.assertGreater(seen["painted"], 0, f"the plant painted no side bar, so this module is blind: {seen}")

    def test_the_tagged_image_carries_the_hidden_default_in_both_bundles(self):
        for bundle in BUNDLES:
            read = run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "grep", self.tag,
                        "-c", "-F", HIDDEN, bundle])
            self.assertEqual(read.stdout.strip(), "1", bundle)


if __name__ == "__main__":
    unittest.main()
