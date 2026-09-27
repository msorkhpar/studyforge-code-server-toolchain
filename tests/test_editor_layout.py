"""The practice frame never paints the Explorer or the secondary side bar — measured from the first frame.

⛔ **The defect this row started from** (reported 2026-09-23): the Explorer side
bar of the code-server frame stayed open until the page had fully loaded, and
only then closed. ⚠️ Measured on code-server 4.137.0 in a real browser: every
frame painted the primary side bar from the workbench's first frame for up to
seven seconds, until the lockdown's `closeSidebar` passes won. ⭐ The image now
starts the side bar CLOSED (`docker/editor/Dockerfile`, the side bar step).

⛔ **The same flash on the other side**: a Java practice frame painted the
secondary side bar, headed "Chat", for about a second and a half while its Java
projects were still opening, and then it went away. ⭐ The image now hides that
bar at every start (the Dockerfile step "THE SECONDARY SIDE BAR NEVER OPENS").

This module reads both the way a reader sees them: every animation frame, from
before the workbench's own first script, on a first start in a fresh browser
profile and again on a reload (`workbench_frames.watch`), never a single end
state.

The static half runs everywhere. ⚠️ The browser half is skipped unless
`TC_DOCKER=1`: it builds the image, starts containers and drives a headless
browser, and a missing browser FAILS it rather than skipping it.

    TC_DOCKER=1 python3 -m unittest tests.test_editor_layout -v

⭐ **Positive controls, planted on the tagged image:** the same image with the
upstream side bar default put back into its bundles must show the Explorer
painted, and with the secondary side bar's start override taken back out must
show that bar painted (each one derived layer, so the plant is provably the
only difference), or this module is blind.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docker" / "editor"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import editor_plan  # noqa: E402
import java_session  # noqa: E402
import workbench_frames  # noqa: E402

BUILD = ROOT / "docker" / "editor" / "build.py"
SET = "java,maven"
DOCKERFILE = (ROOT / editor_plan.DOCKERFILE).read_text(encoding="utf-8")

#: The two workbench bundles that carry the layout's defaults, and what the image sets.
BUNDLES = (
    "/usr/lib/code-server/lib/vscode/out/vs/code/browser/workbench/workbench.js",
    "/usr/lib/code-server/lib/vscode/out/vs/workbench/workbench.web.main.internal.js",
)
HIDDEN = "SIDEBAR_HIDDEN.defaultValue=!0,"
#: What the secondary side bar step inserts at the head of the layout's overrides.
AUX_HIDDEN = "this.applyAuxiliaryBarHiddenOverride(!0);"


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

    def test_the_secondary_side_bar_is_hidden_first_in_both_bundles(self):
        step = DOCKERFILE[DOCKERFILE.index("THE SECONDARY SIDE BAR NEVER OPENS"):]
        step = step[:step.index("\n\n")]
        for bundle in BUNDLES:
            self.assertIn(bundle, step)
        self.assertIn("{AUX}if(this.isNew[1])/".replace("{AUX}", AUX_HIDDEN), step)

    def test_that_step_fails_the_build_unless_exactly_one_override_was_found_and_patched(self):
        step = DOCKERFILE[DOCKERFILE.index("THE SECONDARY SIDE BAR NEVER OPENS"):]
        self.assertIn("layout overrides; this step patches exactly one", step)
        self.assertIn("the secondary side bar's hidden override is not there to call", step)
        self.assertIn("the secondary side bar was not closed at start", step)


@unittest.skipUnless(os.environ.get("TC_DOCKER") == "1", "set TC_DOCKER=1 to build images and run containers")
class NeitherSideBarIsEverPainted(unittest.TestCase):
    """The effect, in a real browser, on the tagged image and on its planted twins."""

    @classmethod
    def setUpClass(cls):
        cls.tag = run([sys.executable, str(BUILD), "--runtimes", SET, "--print-tag"]).stdout.strip()
        built = run([sys.executable, str(BUILD), "--runtimes", SET])
        if built.returncode != 0:
            raise AssertionError(f"the editor build did not pass its own gate:\n{built.stdout}\n{built.stderr}")
        cls.planted: list[str] = []
        cls.tagged: list[dict] | None = None

    @classmethod
    def tearDownClass(cls):
        for image in cls.planted:
            run(["docker", "image", "rm", "-f", image])
        if os.environ.get("TC_KEEP_IMAGES") != "1":
            run(["docker", "image", "rm", "-f", cls.tag])

    def _plant(self, prefix: str, was: str, back: str) -> str:
        """The tagged image with `was` put back to `back` in both bundles, as one derived layer.

        ⛔ It fails unless `was` is in each bundle, so a plant that restored nothing is not read.
        ⭐ `was` is read as a basic regular expression too, where its parentheses are literal
        and each dot matches itself among others; that is exact enough for these two texts."""
        undo = " && ".join(f"grep -qF '{was}' {b} && sed -i 's/{was}/{back}/' {b}" for b in BUNDLES)
        name = java_session.derived(self.tag, prefix, f"RUN {undo}")
        self.planted.append(name)
        return name

    def _tagged(self) -> list[dict]:
        """The tagged image's frame logs, read once for every test here."""
        if type(self).tagged is None:
            type(self).tagged = workbench_frames.watch(self.tag, "layout")
        return type(self).tagged

    def test_the_tagged_image_paints_no_side_bar_from_its_first_frame(self):
        for start, seen in zip(("first start", "reload"), self._tagged()):
            with self.subTest(start=start):
                self.assertGreater(seen["frames"], 100, f"too few frames were watched to say anything: {seen}")
                self.assertEqual(seen["sidebar"], 0, f"the side bar was painted in {seen['sidebar']} frames")

    def test_the_tagged_image_paints_no_secondary_side_bar_from_its_first_frame(self):
        for start, seen in zip(("first start", "reload"), self._tagged()):
            with self.subTest(start=start):
                self.assertGreater(seen["frames"], 100, f"too few frames were watched to say anything: {seen}")
                self.assertEqual(seen["auxiliary"], 0, f"the secondary side bar was painted: {seen}")

    def test_the_upstream_default_planted_back_paints_the_explorer(self):
        image = self._plant("layout-plant", HIDDEN, "SIDEBAR_HIDDEN.defaultValue=!1,")
        first, _ = workbench_frames.watch(image, "layout-plant")
        self.assertGreater(first["sidebar"], 0, f"the plant painted no side bar, so this module is blind: {first}")

    def test_the_start_override_planted_back_out_paints_the_secondary_side_bar(self):
        image = self._plant("layout-aux-plant", AUX_HIDDEN, "")
        for start, seen in zip(("first start", "reload"), workbench_frames.watch(image, "layout-aux-plant")):
            with self.subTest(start=start):
                self.assertGreater(seen["auxiliary"], 0,
                                   f"the plant painted no secondary side bar, so this module is blind: {seen}")

    def test_the_tagged_image_carries_both_edits_in_both_bundles(self):
        for bundle in BUNDLES:
            for edit in (HIDDEN, AUX_HIDDEN):
                read = run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "grep", self.tag,
                            "-c", "-F", edit, bundle])
                self.assertEqual(read.stdout.strip(), "1", f"{bundle}: {edit}")


if __name__ == "__main__":
    unittest.main()
