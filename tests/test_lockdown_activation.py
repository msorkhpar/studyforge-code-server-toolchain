"""The lockdown RUNS — the image's tagging gate, measured both ways.

⛔ Skipped unless `TC_DOCKER=1`: it builds an image, starts containers and
drives a headless browser. Run it as ONE container job:

    TC_DOCKER=1 python3 -m unittest tests.test_lockdown_activation -v

⚠️ **What `tests/test_lockdown.py` cannot see, and why this module exists.**
That module packs the extension, runs it against a stub `vscode` and reads the
packed identity — all true of an extension that the real workbench never runs.
The lockdown's guarantee was that *"an image whose lockdown did not load is not
tagged"*, and the check that carried it read
`code-server --list-extensions`: ⛔ **the extension was installed, listed,
present in `extensions.json`, parsed and inside its engine range while the
extension host activated it in NO session.** ⭐ **So this module asserts the
guarantee on a REAL session in a REAL image, and plants against the gate
itself**: the same image with the Restricted Mode defect put back — no
untrusted-workspace declaration and no `--disable-workspace-trust` — must be
refused although it still passes the installed-list check, and so must an
extension that activates and then throws.

⛔ A browser is NOT optional here: a missing one fails this module rather than
skipping it, because the defect this replaces is a check that passed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docker" / "editor"))

import activation  # noqa: E402
import editor_plan  # noqa: E402

BUILD = ROOT / "docker" / "editor" / "build.py"
#: One set, and the smallest that carries the lockdown: it is installed in
#: EVERY image whatever the set, so a bigger one would only cost minutes.
SET = "java,maven"
LOCKDOWN = editor_plan.lockdown_identity(ROOT)


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, **kwargs)


@unittest.skipUnless(os.environ.get("TC_DOCKER") == "1", "set TC_DOCKER=1 to build images and run containers")
class TheImageIsTaggedOnlyOnceItsLockdownRan(unittest.TestCase):
    """The gate, its plant, and the one line the gate is allowed to be satisfied by."""

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

    def _derive(self, body: str) -> str:
        """The real image with one defect planted on top of it, removed afterwards.

        ⭐ Derived rather than rebuilt: the plant is then provably the ONLY
        difference from the image that passed, and it costs one layer instead
        of a full build.
        """
        name = f"lockdown-plant:{uuid.uuid4().hex[:12]}"
        with tempfile.TemporaryDirectory(prefix="lockdown-plant-") as context:
            Path(context, "Dockerfile").write_text(f"FROM {self.tag}\n{body}\n", encoding="utf-8")
            done = run(["docker", "build", "-t", name, context])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.planted.append(name)
        return name

    def _shipped_cmd(self, without: str = "") -> str:
        """The image's own CMD as a `CMD [...]` line, optionally with one argument taken out."""
        arguments = [a for a in activation.command_of(self.tag)[:-1] if a != without]
        return "CMD [" + ", ".join(f'"{argument}"' for argument in arguments) + "]"

    @property
    def _installed(self) -> str:
        return f"{activation.EXTENSIONS_DIR}/{LOCKDOWN.id}-{LOCKDOWN.version}"

    def test_the_tagged_image_shows_the_lockdown_activating_and_running(self):
        proof = activation.prove(self.tag, LOCKDOWN)
        self.assertTrue(proof.ok, proof.complaint())
        self.assertIn(LOCKDOWN.id, proof.activated)
        self.assertIn(LOCKDOWN.banner, proof.banner)
        # ⭐ The banner names what the extension CLOSED, so the gate is
        # satisfied by work rather than by a line printed on the way in.
        self.assertIn("closeSidebar", proof.banner)

    def test_the_shipped_command_line_is_what_is_proved(self):
        # ⛔ The Restricted Mode defect was a flag the CONTRACT carried and the IMAGE's CMD did not,
        # so a probe with a command line of its own would have proved nothing.
        shipped = activation.command_of(self.tag)
        self.assertIn("--disable-workspace-trust", shipped)
        self.assertEqual(shipped[-1], "--auth=none", "only authentication is added to the shipped command")

    def test_either_half_alone_still_activates_the_lockdown(self):
        # ⭐ MEASURED, and the reason the fix has two halves rather than one.
        # Dropping the image's `--disable-workspace-trust` leaves the manifest's
        # `capabilities.untrustedWorkspaces`, and the extension still runs;
        # the plant below has to take BOTH away. ⚠️ This is the belt and
        # braces asserted rather than asserted about.
        proof = activation.prove(self._derive(self._shipped_cmd(without="--disable-workspace-trust")), LOCKDOWN)
        self.assertTrue(proof.ok, proof.complaint())

    def test_an_image_whose_lockdown_cannot_activate_is_refused_naming_what_was_missing(self):
        # ⛔ THE PLANT, and it reconstructs the Restricted Mode defect exactly: a manifest with no
        # untrusted-workspace declaration, in an image whose command line does
        # not disable workspace trust, against a bind-mounted (untrusted)
        # folder. The extension is still INSTALLED, still listed and still in
        # `extensions.json` -- which is precisely the state the register
        # measured and reported as fixed. The gate must refuse it.
        strip = (f"USER root\nRUN /usr/lib/code-server/lib/node -e \"const f=require('fs'),"
                 f"p='{self._installed}/package.json',m=JSON.parse(f.readFileSync(p,'utf8'));"
                 f"delete m.capabilities;f.writeFileSync(p,JSON.stringify(m))\"\nUSER 1000\n"
                 + self._shipped_cmd(without="--disable-workspace-trust"))
        image = self._derive(strip)
        proof = activation.prove(image, LOCKDOWN)
        self.assertFalse(proof.ok, "an image in Restricted Mode was accepted; the gate reads installation again")
        self.assertIsNone(proof.activated)
        self.assertIsNone(proof.banner)
        self.assertIn("did not run", proof.complaint())
        self.assertIn("_doActivateExtension", proof.log, "the session ran; it never activated the lockdown")
        listed = run(["docker", "run", "--rm", "--entrypoint", "code-server", image,
                      "--extensions-dir", activation.EXTENSIONS_DIR, "--list-extensions"])
        self.assertIn(LOCKDOWN.id, listed.stdout,
                      "the refused image still PASSES the installed-list check, which is the whole finding")

    def test_an_extension_that_activates_and_then_throws_is_refused_too(self):
        # ⛔ The other half of the conjunction. A check that stopped at the
        # workbench's activation line would tag this image: the line is there.
        broken = (f"USER root\nRUN printf '%s' \"module.exports={{activate(){{throw new Error('planted');}},"
                  f"deactivate(){{}}}};\" > {self._installed}/extension.js\nUSER 1000")
        proof = activation.prove(self._derive(broken), LOCKDOWN)
        self.assertFalse(proof.ok, "an extension that threw on activation was accepted")
        self.assertIsNotNone(proof.activated, "the workbench did activate it; that is the point")
        self.assertIsNone(proof.banner)

    def test_the_build_refuses_to_tag_when_there_is_no_browser_to_prove_with(self):
        # ⭐ A gate that can be absent is not a gate. An empty PATH for the
        # browser lookup must REFUSE, naming what it looked for.
        with self.assertRaises(activation.Refused) as refusal:
            activation.browser({activation.BROWSER_ENV: "/nonexistent/no-such-browser"})
        self.assertIn("not an executable", str(refusal.exception))

    def test_the_probe_leaves_no_container_behind(self):
        before = run(["docker", "ps", "-aq", "--filter", "name=lockdown-probe-"]).stdout.split()
        activation.prove(self.tag, LOCKDOWN)
        after = run(["docker", "ps", "-aq", "--filter", "name=lockdown-probe-"]).stdout.split()
        self.assertEqual(sorted(before), sorted(after))


if __name__ == "__main__":
    unittest.main()
