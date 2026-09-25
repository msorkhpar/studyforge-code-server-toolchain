"""A changed editor is never run from a browser's cache, and an unchanged one is never downloaded again.

⛔ **The reading this module started from** (found live after the chat was
taken out of the product): a browser that had loaded one editor image kept
showing "Chat" and "Copilot status" on the next. It had run the old
`workbench.js` from its cache (`transferSize` 0). The workbench is served under
`/stable-<commit>/static/` with `Cache-Control: public, max-age=31536000`, and
that commit was code-server's own: the same for every image built on one
release. ⭐ The image now rewrites the commit to a digest of the product's files
(`docker/editor/Dockerfile`, the static path step), and this module reads it
the way a reader meets it: ONE browser, ONE origin, one image and then the
next on the same port, with no cache cleared in between.

1. **A then B**, where B carries one more edit to the product: B's
   `workbench.js` arrives over the network, and B's edit is what runs.
2. **A then A'**, where A' differs from A only OUTSIDE the product (an `ENV`):
   the same static path, and `workbench.js` comes from the cache.

The static half runs everywhere. ⚠️ The browser half is skipped unless
`TC_DOCKER=1`: it builds three images (the tree, and two planted copies of its
inputs), starts containers and drives a headless browser, and a missing
browser FAILS it rather than skipping it.

    TC_DOCKER=1 python3 -m unittest tests.test_editor_static_path -v

⭐ **The positive control is the defect itself:** with the step planted out, A
and B share one path, and reading 1 must fail.
"""

from __future__ import annotations

import os
import re
import socket
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
import editor_plan  # noqa: E402
import probe  # noqa: E402

SET = "java,maven"
WORK = ROOT / ".work" / "tests-static-path"
DOCKERFILE = (ROOT / editor_plan.DOCKERFILE).read_text(encoding="utf-8")
PRODUCT = "/usr/lib/code-server/lib/vscode/product.json"
BUNDLE = "/usr/lib/code-server/lib/vscode/out/vs/code/browser/workbench/workbench.js"

#: The step, as the Dockerfile opens it.
STEP = "THE STATIC PATH CHANGES WHENEVER THE PRODUCT'S FILES DO"
#: Steps that write the product, each by a phrase of its own; the static path step must follow all of them.
PRODUCT_EDITS = ("THE BUNDLED CHAT IS DELETED FROM THE PRODUCT", "THE AGENT HOST THAT RAN IT IS OFF",
                 "THE WORKBENCH'S OWN CHAT IS TAKEN OUT", "THE PRIMARY SIDE BAR STARTS CLOSED",
                 "THE EDITOR DRAWS CODE IN THE PAGE'S FACE")

#: B's one extra edit to the product, placed before the static path step, and what it leaves in the page.
MARKER = "__studyforgeStaticPathB"
EDIT_B = f"RUN printf '\\n;globalThis.{MARKER}=1;\\n' >> {BUNDLE}\n\n"
#: A''s one change, outside the product.
EDIT_A2 = "ENV STUDYFORGE_STATIC_PATH_PROBE=1\n"

READ = r"""(() => {
  const js = performance.getEntriesByType('resource').filter((r) => /\/workbench\.js(\?|$)/.test(r.name));
  return {marker: !!globalThis.%s,
          workbench: js.map((r) => ({path: new URL(r.name).pathname, transfer: r.transferSize}))};
})()""" % MARKER


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, **kwargs)


def step_at(text: str, phrase: str) -> int:
    at = text.find(phrase)
    if at < 0:
        raise AssertionError(f"the Dockerfile has no step saying {phrase!r}")
    return at


def copy_with(name: str, before_step: str = "", after_step: str = "") -> Path:
    """A copy of the build's inputs with one line placed before or after the static path step."""
    target = build_inputs.copy_inputs(WORK / name)
    path = target / editor_plan.DOCKERFILE
    text = path.read_text(encoding="utf-8")
    start = text.index(f"# ⛔ {STEP}")
    end = text.index("\n\n", text.index("RUN --network=none set -eu;", start)) + 2
    path.write_text(text[:start] + before_step + text[start:end] + after_step + text[end:], encoding="utf-8")
    return target


def build(root: Path) -> str:
    tool = root / "docker" / "editor" / "build.py"
    done = run([sys.executable, str(tool), "--root", str(root), "--runtimes", SET, "--pull", "never"])
    if done.returncode != 0:
        raise AssertionError(f"{root.name}: the editor build did not pass its own gate:\n{done.stdout[-3000:]}"
                             f"\n{done.stderr[-3000:]}")
    return run([sys.executable, str(tool), "--root", str(root), "--runtimes", SET, "--print-tag"]).stdout.strip()


def static_path(image: str) -> str:
    read = run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "cat", image, PRODUCT])
    found = re.findall(r'"commit":\s*"([0-9a-f]+)"', read.stdout)
    if len(found) != 1:
        raise AssertionError(f"{image}: product.json names {len(found)} commits")
    return f"/stable-{found[0]}/"


def free_port() -> int:
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        return held.getsockname()[1]


class TheStepIsInTheBuild(unittest.TestCase):
    """What a text can establish: the step is there, follows every product edit, and refuses a miss."""

    def test_it_follows_every_step_that_writes_the_product(self):
        step = step_at(DOCKERFILE, STEP)
        for edit in PRODUCT_EDITS:
            self.assertLess(step_at(DOCKERFILE, edit), step, f"{edit!r} writes the product after its digest")
        later = DOCKERFILE[step:]
        later = later[later.index("\n\n"):]
        self.assertNotIn("/usr/lib/code-server", later, "a step after the digest touches the product")

    def test_the_digest_is_of_the_files_and_rewrites_every_copy_of_the_commit(self):
        step = DOCKERFILE[step_at(DOCKERFILE, STEP):]
        step = step[:step.index("\n\n", step.index("RUN --network=none set -eu;"))]
        self.assertIn('find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum', step)
        self.assertIn('grep -rlF "$was" "$vscode" | xargs sed -i "s/$was/$now/g"', step)
        self.assertIn("the old commit is still in", step)
        self.assertIn("this step rewrites exactly one", step)


@unittest.skipUnless(os.environ.get("TC_DOCKER") == "1", "set TC_DOCKER=1 to build images and run containers")
class ABrowserRunsTheImageItIsServed(unittest.TestCase):
    """One browser and one origin: A, then B or A', with no cache cleared."""

    @classmethod
    def setUpClass(cls):
        cls.a = build(ROOT)
        cls.b = build(copy_with("b", before_step=EDIT_B))
        cls.a2 = build(copy_with("a2", after_step=EDIT_A2))

    @classmethod
    def tearDownClass(cls):
        if os.environ.get("TC_KEEP_IMAGES") != "1":
            for image in (cls.a, cls.b, cls.a2):
                run(["docker", "image", "rm", "-f", image])

    def _one_browser(self, first: str, then: str) -> tuple[dict, dict]:
        """Load `first`, replace its container by `then` on the SAME port, and load again in the same tab."""
        port, debug, readings, name = free_port(), free_port(), [], None
        with tempfile.TemporaryDirectory(prefix="static-path-") as scratch:
            sources = Path(scratch) / "sources"
            sources.mkdir()
            (sources / probe.MAIN).write_text(probe.MAIN_TEXT, encoding="utf-8")
            Path(scratch).chmod(0o755)
            browser = subprocess.Popen(
                [activation.browser(), *activation.BROWSER_FLAGS, f"--remote-debugging-port={debug}",
                 f"--user-data-dir={Path(scratch) / 'profile'}", "about:blank"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                page = cdp.wait_for_target(debug, "about:blank")
                with cdp.Session(page["webSocketDebuggerUrl"]) as session:
                    session.call("Page.enable")
                    session.call("Runtime.enable")
                    for image in (first, then):
                        name = f"static-path-{uuid.uuid4().hex[:12]}"
                        run(["docker", "run", "-d", "--name", name, "--init", "--user", f"{os.getuid()}:{os.getgid()}",
                             "-p", f"127.0.0.1:{port}:8080", "--tmpfs", "/home/coder/repo",
                             "-v", f"{sources}:{activation.SOURCES}", image, *activation.command_of(image)], check=True)
                        activation.wait_for_health(port)
                        # ⚠️ Through a blank page, so the reading below can never be the previous document's.
                        session.call("Page.navigate", {"url": "about:blank"})
                        time.sleep(1.0)
                        session.call("Page.navigate", {"url": activation.workbench_url(port, name=probe.MAIN)})
                        time.sleep(2.0)
                        probe.wait_for_editor(session)
                        readings.append(cdp.evaluate(session, READ))
                        run(["docker", "rm", "-f", name])
                        name = None
            finally:
                browser.terminate()
                browser.wait(timeout=20)
                if name:
                    run(["docker", "rm", "-f", name])
        return readings[0], readings[1]

    def test_a_then_b_runs_bs_files_fetched_over_the_network(self):
        self.assertNotEqual(static_path(self.a), static_path(self.b), "an edit to the product kept its path")
        first, then = self._one_browser(self.a, self.b)
        self.assertEqual(len(first["workbench"]), 1, first)
        self.assertGreater(first["workbench"][0]["transfer"], 0, f"A's first load came from a cache: {first}")
        self.assertFalse(first["marker"], "A runs B's edit, so the two images are not what they say")
        self.assertEqual(len(then["workbench"]), 1, then)
        self.assertTrue(then["workbench"][0]["path"].startswith(static_path(self.b)), then)
        self.assertGreater(then["workbench"][0]["transfer"], 0, f"B's workbench.js came from the cache: {then}")
        self.assertTrue(then["marker"], f"the browser ran A's workbench against B: {then}")

    def test_a_then_an_image_with_the_same_product_downloads_nothing_again(self):
        self.assertNotEqual(self.a, self.a2, "the change outside the product did not make a second image")
        self.assertEqual(static_path(self.a), static_path(self.a2), "identical product files, different paths")
        first, then = self._one_browser(self.a, self.a2)
        self.assertEqual(first["workbench"][0]["path"], then["workbench"][0]["path"])
        self.assertEqual(then["workbench"][0]["transfer"], 0, f"an unchanged workbench was downloaded again: {then}")


if __name__ == "__main__":
    unittest.main()
