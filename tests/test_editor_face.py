"""The editor draws code in the study page's face and weight — read from the glyphs the browser drew.

⛔ **The reading this row started from:** the study page sets code in JetBrains
Mono, regular with bold keywords, and the editor drew its own default
monospace. ⭐ The image now SERVES the page's two face files beside the
workbench's stylesheet and declares them there (`docker/editor/Dockerfile`, the
face step), and the lockdown's manifest makes the family the editor's default
(`configurationDefaults`). A face the image held on disk would never reach the
reader: the browser draws the workbench.

⭐ **The instrument is the renderer's own answer**, `CSS.getPlatformFontsForNode`:
the font file the browser used for a token's glyphs, never the CSS that asked
for one. A family that failed to load still reads as asked for in CSS.

The static half runs everywhere. ⚠️ The browser half is skipped unless
`TC_DOCKER=1`, and a missing browser FAILS it rather than skipping it.

    TC_DOCKER=1 python3 -m unittest tests.test_editor_face -v

⭐ **Two positive controls, each planted on the tagged image as one derived
layer:** the declaration taken out of the stylesheet, and the default taken out
of the manifest. Each must draw a face that is not the page's, or this is blind.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docker" / "editor"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cdp  # noqa: E402
import editor_plan  # noqa: E402
import face  # noqa: E402
import java_session  # noqa: E402

BUILD = ROOT / "docker" / "editor" / "build.py"
SET = "java,maven"
DOCKERFILE = (ROOT / editor_plan.DOCKERFILE).read_text(encoding="utf-8")
EPINS = editor_plan.load(ROOT)
MANIFEST = json.loads((ROOT / "lockdown" / "package.json").read_text(encoding="utf-8"))
WORKBENCH = "/usr/lib/code-server/lib/vscode/out/vs/code/browser/workbench"
#: The PostScript names of the page's two faces, as the renderer reports them.
REGULAR, BOLD = "JetBrainsMono-Regular", "JetBrainsMono-Bold"
#: The key `_drawn` records the ligature reading under: whether `!=` drew
#: differently once its ligatures were turned off.
LIGATURES = "(ligatures)"

#: The first `!=` the editor drew, marked so the DOM domain can find it, and its box.
OPERATOR = """(() => { const el = [...document.querySelectorAll('.monaco-editor .view-line span span')]
  .find((span) => span.textContent.trim() === '!=');
  if (!el) { return null; }
  el.setAttribute('data-face-ligature', '1');
  const r = el.getBoundingClientRect();
  return {x: r.x, y: r.y, width: r.width, height: r.height, scale: 1}; })()"""
#: The same span with every ligature turned off, which is what the page would
#: draw if it drew none.
UNJOINED = """(() => { const el = document.querySelector('[data-face-ligature]');
  el.style.fontVariantLigatures = 'none'; el.style.fontFeatureSettings = '"liga" 0, "calt" 0'; })()"""

#: Every token span in the editor, with its text, its computed weight and a
#: selector path the DOM domain can resolve.
TOKENS = """(() => [...document.querySelectorAll('.monaco-editor .view-line span span')]
  .map((el, i) => { el.setAttribute('data-face-probe', String(i));
                    return {i, text: el.textContent, weight: getComputedStyle(el).fontWeight}; }))()"""


class TheFaceIsPinnedAndDeclared(unittest.TestCase):
    """What a text can establish: the pins, the extraction, the declaration and the default."""

    def test_the_faces_are_the_page_release_regular_and_bold_with_the_licence(self):
        pinned = EPINS["face"]
        self.assertEqual(pinned["family"], face.FAMILY)
        weights = sorted(entry["weight"] for entry in pinned["files"].values())
        self.assertEqual(weights, ["400", "700", "licence"])
        self.assertEqual(editor_plan.pins_findings(EPINS), [])

    def test_the_archive_arrives_by_its_recorded_checksum_and_every_set_gets_it(self):
        self.assertIn("ADD --checksum=sha256:${FACE_SHA256} ${FACE_URL} /face.zip", DOCKERFILE)
        for names in (("java", "maven"), ("python",)):
            plan = editor_plan.plan(editor_plan.runner_plan.load(ROOT), EPINS,
                                    editor_plan.runner_plan.plan(editor_plan.runner_plan.load(ROOT), names,
                                                                 "linux/amd64", "0" * 64), "0" * 64)
            self.assertEqual(plan.build_args["FACE_SHA256"], EPINS["face"]["sha256"])
            self.assertEqual(len(plan.build_args["FACE_FILES"].splitlines()), 3)

    def test_the_rules_declare_each_weight_by_a_url_beside_the_stylesheet(self):
        rules = face.rules([("fonts/webfonts/A-Regular.woff2", "400", "0"), ("OFL.txt", "licence", "0"),
                            ("fonts/webfonts/A-Bold.woff2", "700", "0")])
        self.assertTrue(rules.startswith(face.MARKER))
        self.assertIn('font-weight:400;font-display:block;src:url("faces/A-Regular.woff2")', rules)
        self.assertIn('font-weight:700;font-display:block;src:url("faces/A-Bold.woff2")', rules)
        self.assertNotIn("OFL", rules)
        self.assertNotIn("data:", rules, "the workbench's font-src allows its own origin only")

    def test_a_file_that_is_not_the_pinned_bytes_is_refused_naming_it(self):
        with tempfile.TemporaryDirectory() as scratch:
            archive = Path(scratch) / "face.zip"
            with zipfile.ZipFile(archive, "w") as release:
                release.writestr("fonts/webfonts/A-Regular.woff2", b"planted bytes")
            lines = Path(scratch) / "lines.txt"
            good = hashlib.sha256(b"planted bytes").hexdigest()
            lines.write_text(f"fonts/webfonts/A-Regular.woff2|400|{good}\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(face.main([str(archive), str(lines), str(Path(scratch) / "ok")]), 0)
            lines.write_text(f"fonts/webfonts/A-Regular.woff2|400|{'0' * 64}\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as said:
                self.assertEqual(face.main([str(archive), str(lines), str(Path(scratch) / "no")]), 1)
            self.assertIn("A-Regular.woff2", said.getvalue())

    def test_the_declaration_is_appended_once_or_the_build_fails(self):
        self.assertIn('cat "$dir/faces/faces.css" >> "$dir/workbench.css"', DOCKERFILE)
        self.assertIn(face.MARKER, DOCKERFILE)
        self.assertIn("the code face is not declared exactly once", DOCKERFILE)

    def test_the_editor_default_family_is_the_page_face_first(self):
        family = MANIFEST["contributes"]["configurationDefaults"]["editor.fontFamily"]
        self.assertTrue(family.startswith(f"'{face.FAMILY}'"), family)

    def test_the_editor_draws_no_ligature_by_default_as_the_page_does(self):
        """The page sets `font-variant-ligatures: none` on code, because `!=` joined into
        a not-equal sign misleads in code; the editor matches it."""
        self.assertIs(MANIFEST["contributes"]["configurationDefaults"]["editor.fontLigatures"], False)


@unittest.skipUnless(os.environ.get("TC_DOCKER") == "1", "set TC_DOCKER=1 to build images and run containers")
class TheEditorDrawsThePageFace(unittest.TestCase):
    """The effect, in a real browser, on the tagged image and on its two planted twins."""

    @classmethod
    def setUpClass(cls):
        cls.tag = java_session.run([sys.executable, str(BUILD), "--runtimes", SET, "--print-tag"]).stdout.strip()
        built = java_session.run([sys.executable, str(BUILD), "--runtimes", SET])
        if built.returncode != 0:
            raise AssertionError(f"the editor build did not pass its own gates:\n{built.stdout}\n{built.stderr}")
        cls.planted: list[str] = []

    @classmethod
    def tearDownClass(cls):
        for image in cls.planted:
            java_session.run(["docker", "image", "rm", "-f", image])
        if os.environ.get("TC_KEEP_IMAGES") != "1":
            java_session.run(["docker", "image", "rm", "-f", cls.tag])

    def _plant(self, steps: str) -> str:
        image = java_session.derived(self.tag, "face-plant", steps)
        self.planted.append(image)
        return image

    def _drawn(self, image: str) -> dict:
        """{token text: (the PostScript names the renderer drew it with, computed weight)}."""
        with java_session.opened(image, "face") as page, cdp.Session(page.page["webSocketDebuggerUrl"]) as s:
            for domain in ("Page", "Runtime", "DOM", "CSS"):
                s.call(f"{domain}.enable")
            s.call("Page.navigate", {"url": page.url})
            deadline = time.monotonic() + java_session.activation.HEALTH_TIMEOUT
            while not any(t["text"] == "public" for t in cdp.evaluate(s, TOKENS) or []):
                self.assertLess(time.monotonic(), deadline, "the workbench never drew the practice's tokens")
                time.sleep(1)
            time.sleep(8)  # the faces load and the editor re-measures before the reading
            drawn = {}
            root = s.call("DOM.getDocument", {"depth": -1})["root"]["nodeId"]
            for token in cdp.evaluate(s, TOKENS):
                if not token["text"].strip() or token["text"] in drawn:
                    continue
                node = s.call("DOM.querySelector", {"nodeId": root,
                                                    "selector": f'[data-face-probe="{token["i"]}"]'})["nodeId"]
                fonts = s.call("CSS.getPlatformFontsForNode", {"nodeId": node})["fonts"]
                drawn[token["text"]] = (sorted(f["postScriptName"] for f in fonts), token["weight"])
            box = cdp.evaluate(s, OPERATOR)
            self.assertIsNotNone(box, "the editor drew no `!=`, so the ligature reading reads nothing")
            joined = s.call("Page.captureScreenshot", {"format": "png", "clip": box})["data"]
            cdp.evaluate(s, UNJOINED)
            time.sleep(0.5)
            apart = s.call("Page.captureScreenshot", {"format": "png", "clip": box})["data"]
            drawn[LIGATURES] = joined != apart
            return drawn

    def test_the_tagged_image_draws_plain_code_regular_and_keywords_bold_in_the_page_face(self):
        drawn = self._drawn(self.tag)
        self.assertEqual(drawn["value"], ([REGULAR], "400"), drawn)
        self.assertEqual(drawn["twice"], ([REGULAR], "400"), drawn)
        for keyword in ("public", "class", "return"):
            self.assertEqual(drawn[keyword], ([BOLD], "700"), drawn)
        self.assertFalse(drawn[LIGATURES], f"`!=` drew differently with its ligatures off: one was drawn: {drawn}")

    def test_the_declaration_planted_out_draws_another_face(self):
        drawn = self._drawn(self._plant(f"RUN sed -i '/studyforge: the page.s code face/,$d' {WORKBENCH}/workbench.css"))
        self.assertNotIn(REGULAR, drawn["value"][0], f"the plant still drew the page face, so this is blind: {drawn}")

    def test_the_ligature_default_planted_on_draws_one(self):
        drawn = self._drawn(self._plant(
            "RUN sed -i 's/\"editor.fontLigatures\": false/\"editor.fontLigatures\": true/' "
            "/opt/code-server/extensions/studyforge.practice-focus-*/package.json"))
        self.assertEqual(drawn["value"], ([REGULAR], "400"), f"the plant changed the face as well: {drawn}")
        self.assertTrue(drawn[LIGATURES], f"the plant drew no ligature, so this reading is blind: {drawn}")

    def test_the_default_planted_out_draws_another_face(self):
        drawn = self._drawn(self._plant(
            "RUN sed -i 's/\"configurationDefaults\"/\"notConfigurationDefaults\"/' "
            "/opt/code-server/extensions/studyforge.practice-focus-*/package.json"))
        self.assertNotIn(REGULAR, drawn["value"][0], f"the plant still drew the page face, so this is blind: {drawn}")


if __name__ == "__main__":
    unittest.main()
