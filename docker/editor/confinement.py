"""Prove the workbench ALLOWS nothing outside the practice, before the image is tagged (W433).

**What it does.** `prove(image)` starts a container from `image` with the
image's own command line, opens a workbench in a headless browser at the URL a
study page builds, and then **is the reader**: it presses `Ctrl+Shift+P`,
`Ctrl+P`, `Ctrl+,`, `F5` and the rest at a real session and looks at the page
for what appeared. It then presses the keys a practice NEEDS -- find, type,
save -- and checks those still work. `Confinement.ok` is true only when every
confined chord opened nothing AND the practice still edits and saves.

**Why it is keys and pixels rather than a file.** `W433` confines by
keybinding; the keybindings live in a file; and a check that reads that file
cannot see what the workbench ALLOWS. ⛔ That is the exact shape of the error
`W432` exists because of, where a check that read INSTALLATION could not see
ACTIVATION and passed for five rounds against a broken product. ⚠️ It would
have been especially wrong here: measured, the workbench reads the user
keybindings file when a session STARTS and ignores a write made while one is
open, so a correct file on disk and a confined session are different facts.

**The other half.** This one is BEHAVIOURAL and samples -- the chords
`CONFINED` names, not all four hundred. The EXHAUSTIVE half is the extension's
own report, which derives the removals the allow-list implies from the
workbench's own keybinding document and says how many the session did not
load; this refuses on `missing=`. ⭐ Together: *does the seed still cover this
workbench*, and *does this workbench actually refuse*.

**How you use it.** `docker/editor/build.py` runs it after `activation.py` and
tags only if both pass. It also runs standalone:

    python3 docker/editor/confinement.py [--write] <image reference>

⭐ `--write` is the GENERATOR: it opens the same session and copies what the
extension derived into `docker/editor/seed/keybindings.json`. ⛔ The seed is
never hand-edited -- `lockdown/allowed.js` is the allow-list and everything
else is computed. ⚠️ It UNIONS rather than replaces, for the measurement
`lockdown/keybindings.js` carries: the workbench's default keybinding document
is not the same in two sessions of one image, so a regeneration that replaced
would oscillate and drop what another session found.

**Depends on.** The standard library, `activation.py` beside it for the
container and the browser, `cdp.py` for the protocol, a Docker CLI and a
Chromium-family browser. ⛔ A missing browser REFUSES rather than skips, for
`activation.py`'s reason. ⛔ No Docker socket is mounted (spec §8.3).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPONENT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(COMPONENT / "lockdown"))
import activation  # noqa: E402
import cdp  # noqa: E402
import lockdown as lockdown_extension  # noqa: E402

Refused = activation.Refused

#: The generated seed the image bakes in, relative to the component root.
SEED = Path("docker/editor/seed/keybindings.json")

#: The chords this presses, and what each of them is. ⛔ The first of them are
#: the ones the reader's own screenshot named; the rest are the surfaces around
#: the editor, which `W432` could only close after the fact. ⚠️ `Run Task` has
#: NO default keybinding at all -- it is reachable only THROUGH the palette, so
#: closing the palette closes it and there is no chord to press for it.
CONFINED = (
    ("ctrl+p", "Go to File"),
    ("ctrl+e", "Go to File, the other chord"),
    ("ctrl+shift+p", "Show and Run Commands"),
    ("f1", "Show and Run Commands, the other chord"),
    ("ctrl+shift+f", "Search for Text"),
    ("ctrl+shift+alt+l", "Open Quick Chat"),
    ("ctrl+shift+o", "Go to Symbol in Editor"),
    ("f5", "Start Debugging"),
    ("ctrl+,", "Preferences: Open Settings"),
    ("ctrl+g", "Go to Line"),
    ("ctrl+b", "the primary side bar"),
    ("ctrl+shift+e", "the Explorer"),
    ("ctrl+shift+d", "Run and Debug"),
    ("ctrl+shift+x", "Extensions"),
    ("ctrl+`", "the integrated terminal"),
    ("ctrl+j", "the panel"),
    ("ctrl+shift+u", "the Output panel"),
)

#: What a surface looks like in the page, and what to call it in a refusal. ⭐
#: Read by COMPUTED STYLE and size, never by presence: the workbench keeps the
#: quick input's element in the document and hides it, so `querySelector` alone
#: would report the palette open in every session.
SURFACES = {
    ".quick-input-widget": "the command palette / quick open",
    ".settings-editor": "the settings editor",
    ".part.sidebar": "the primary side bar",
    ".part.panel": "the panel",
    ".part.auxiliarybar": "the secondary side bar",
}

#: The one surface a practice DOES need, and the chord that opens it. ⛔ Not a
#: nicety: a check that only ever sees nothing cannot tell a confined
#: workbench from a browser that never delivered a keystroke.
ALLOWED_CHORD = ("ctrl+f", ".editor-widget.find-widget", "the editor's own find widget")

#: The probe workspace -- the file the URL opens, a second one to be tempted
#: by, and what is typed into the first, which must reach the disk.
MAIN, OTHER = "practice.txt", "judge.txt"
MAIN_TEXT = "The confinement probe edits this file. It belongs to no corpus.\n"
OTHER_TEXT = "The confinement probe never opens this one.\n"
TYPED = "probe-edit"

SETTLE = 1.4
READY_TIMEOUT = 180.0


@dataclass(frozen=True)
class Confinement:
    """What a real session did when the keys were pressed. ⭐ `ok` is the conjunction."""

    image: str
    #: chord -> the surfaces that appeared, empty when the chord did nothing.
    opened: dict = field(default_factory=dict)
    #: Whether the practice's own find widget still opens.
    find: bool = False
    #: Whether typing reached the file ON DISK through the editor's save.
    edited: bool = False
    #: The extension's own line, which carries `missing=` and `extra=`.
    report: str = ""

    def _counted(self, name: str) -> int:
        found = re.search(rf"{name}=(\d+)", self.report)
        return int(found.group(1)) if found else -1

    @property
    def missing(self) -> int:
        """Removals THIS session's workbench needs that it did not load. ⛔ The refusal."""
        return self._counted("missing")

    @property
    def extra(self) -> int:
        """Removals it loaded whose command the allow-list now permits -- the practice, over-confined."""
        return self._counted("extra")

    @property
    def reached(self) -> list:
        return sorted(chord for chord, surfaces in self.opened.items() if surfaces)

    @property
    def ok(self) -> bool:
        return (not self.reached and self.find and self.edited
                and self.missing == 0 and self.extra == 0)

    def complaint(self) -> str:
        wrong = []
        for chord in self.reached:
            wrong.append(f"{chord} opened {', '.join(self.opened[chord])}")
        if not self.find:
            wrong.append(f"{ALLOWED_CHORD[0]} did not open {ALLOWED_CHORD[2]}, so the practice is broken "
                         "and this check cannot tell a confined session from a dead one")
        if not self.edited:
            wrong.append("what the probe typed never reached the file on disk, so the practice cannot be done")
        if self.missing != 0:
            wrong.append(f"the extension reports {self.missing} keybinding removals the session did not load "
                         f"-- the seed no longer covers this workbench ({self.report or 'no report at all'})")
        elif self.extra != 0:
            wrong.append(f"the extension reports {self.extra} loaded removals whose command the allow-list "
                         f"now permits -- the seed takes something away from the practice ({self.report})")
        return f"{self.image}: the practice frame is not confined -- {'; '.join(wrong)}"


def free_port() -> int:
    """A port nothing is listening on, for the browser's debugger."""
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        return held.getsockname()[1]


@contextlib.contextmanager
def session(image: str, kind: str):
    """One container of `image`, one practice-shaped folder and one browser at its workbench.

    ⭐ The setup both readings need, so neither can drift from the other: the
    behavioural proof and the generator must open the SAME shape of session or
    what the one measures is not what the other writes down.
    """
    found = activation.browser()
    name = f"{kind}-probe-{uuid.uuid4().hex[:12]}"
    with tempfile.TemporaryDirectory(prefix=f"{kind}-probe-") as scratch:
        sources = Path(scratch) / "sources"
        sources.mkdir()
        (sources / MAIN).write_text(MAIN_TEXT, encoding="utf-8")
        (sources / OTHER).write_text(OTHER_TEXT, encoding="utf-8")
        Path(scratch).chmod(0o755)
        try:
            activation.start(image, name, sources)
            port = activation.published_port(name)
            activation.wait_for_health(port)
            with _browser(found, port, Path(scratch) / "profile") as debug:
                yield name, port, debug
        finally:
            subprocess.run(["docker", "rm", "-f", name], stdin=subprocess.DEVNULL, capture_output=True)


def prove(image: str, lock=None) -> Confinement:
    """Open a real session in `image` and press the keys a reader would."""
    lock = lock or lockdown_extension.identity(COMPONENT / "lockdown")
    with session(image, "confinement") as (name, port, debug):
        return _drive(image, name, port, lock, debug)


def derived(image: str, lock=None) -> list:
    """What the extension derives from THIS image's workbench, for `--write` to save.

    ⭐ The derivation is the extension's, never re-implemented here: the
    allow-list is JavaScript, it runs inside the workbench that owns the
    default keybindings, and this only carries the answer out. ⚠️ What it
    carries is already the UNION of this session's derivation and the seed the
    image booted with, so writing it over the seed can only add.
    """
    lock = lock or lockdown_extension.identity(COMPONENT / "lockdown")
    with session(image, "keybindings") as (name, _, _debug):
        return _wait_for_derived(name, lock)


class _browser:
    """The headless browser, with its debugger open, for as long as the probe needs it."""

    def __init__(self, found: str, port: int, profile: Path):
        self.debug = free_port()
        url = activation.workbench_url(port, name=MAIN)
        self.session = subprocess.Popen(
            [found, *activation.BROWSER_FLAGS, f"--remote-debugging-port={self.debug}",
             f"--user-data-dir={profile}", url],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def __enter__(self) -> int:
        return self.debug

    def __exit__(self, *_) -> None:
        self.session.terminate()
        try:
            self.session.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.session.kill()


#: The page probe: which surfaces are visibly open right now. ⚠️ `width > 2`
#: rather than `> 0`, because a closed part keeps a one-pixel sash.
_VISIBLE = """(() => {
  const open = [];
  for (const [selector, name] of %s) {
    for (const element of document.querySelectorAll(selector)) {
      const style = getComputedStyle(element), box = element.getBoundingClientRect();
      if (style.display !== 'none' && style.visibility !== 'hidden' && box.width > 2 && box.height > 2) {
        open.push(name); break;
      }
    }
  }
  return open;
})()"""

_EDITOR_BOX = """(() => {
  const lines = document.querySelector('.monaco-editor .view-lines');
  if (!lines) { return null; }
  const box = lines.getBoundingClientRect();
  if (box.width < 10 || box.height < 5) { return null; }
  return {x: Math.round(box.x + 20), y: Math.round(box.y + 6)};
})()"""


def _surfaces(session, pairs=None) -> list:
    return cdp.evaluate(session, _VISIBLE % json.dumps(list((pairs or SURFACES).items())))


def _drive(image: str, name: str, port: int, lock, debug: int) -> Confinement:
    """Press every confined chord, then the practice's own, then type and save."""
    page = cdp.wait_for_target(debug, f":{port}/")
    with cdp.Session(page["webSocketDebuggerUrl"]) as session:
        session.call("Runtime.enable")
        box = _wait_for_editor(session)
        opened = {}
        for chord, _ in CONFINED:
            cdp.click(session, box["x"], box["y"])
            cdp.press(session, chord)
            time.sleep(SETTLE)
            opened[chord] = _surfaces(session)
            cdp.press(session, "escape")
            time.sleep(0.4)
        chord, selector, label = ALLOWED_CHORD
        cdp.click(session, box["x"], box["y"])
        cdp.press(session, chord)
        time.sleep(SETTLE)
        find = bool(_surfaces(session, {selector: label}))
        cdp.press(session, "escape")
        time.sleep(0.4)
        edited = _edit_and_save(session, name, box)
    return Confinement(image=image, opened=opened, find=find, edited=edited,
                       report=_report(name, lock))


def _wait_for_editor(session) -> dict:
    """The editor's own text area, once the workbench has opened the URL's file."""
    deadline = time.monotonic() + READY_TIMEOUT
    while time.monotonic() < deadline:
        box = cdp.evaluate(session, _EDITOR_BOX)
        if box:
            time.sleep(4.0)  # let the lockdown's own closing passes settle first
            return box
        time.sleep(2.0)
    raise Refused(f"the workbench never showed an editor for {MAIN} within {READY_TIMEOUT:.0f}s")


def _edit_and_save(session, name: str, box: dict) -> bool:
    """Type into the one file and save it, and answer whether the disk changed.

    ⛔ Read back through `docker exec`, from the container's own copy of the
    file: the point is that the reader's edit reaches the disk a Run and a
    Submit execute against, and only the container can say that.
    """
    cdp.click(session, box["x"], box["y"])
    cdp.press(session, "ctrl+end")
    time.sleep(0.4)
    cdp.type_text(session, f"\n{TYPED}\n")
    time.sleep(0.6)
    cdp.press(session, "ctrl+s")
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        read = subprocess.run(["docker", "exec", name, "cat", f"{activation.SOURCES}/{MAIN}"],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True)
        if TYPED in read.stdout:
            return True
        time.sleep(1.5)
    return False


def _report(name: str, lock) -> str:
    """The extension's own keybinding line out of the session's log."""
    for line in activation.exthost_log(name, lock).splitlines():
        if line.startswith(f"{lock.banner} keybindings:"):
            return line.strip()
    return ""


def _wait_for_derived(name: str, lock, timeout: float = activation.ACTIVATION_TIMEOUT) -> list:
    """What the extension wrote beside its log, once the session has activated it."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        read = subprocess.run(
            ["docker", "exec", name, "sh", "-c",
             f"cat {activation.LOGS}/*/exthost*/{lock.id}/{lockdown_extension.DERIVED_KEYBINDINGS} 2>/dev/null"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True)
        if read.stdout.strip():
            entries = json.loads(read.stdout)
            if entries:
                return entries
        time.sleep(activation.POLL)
    raise Refused(f"the lockdown derived no keybinding removals in {timeout:.0f}s; "
                  "either it did not activate, or the workbench's default list could not be read")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", help="the editor image reference or id to open a session in")
    parser.add_argument("--write", action="store_true",
                        help=f"regenerate {SEED} from that image's workbench instead of checking it")
    parser.add_argument("--root", default=str(COMPONENT))
    args = parser.parse_args(argv)
    try:
        if args.write:
            entries = derived(args.image)
            target = Path(args.root) / SEED
            target.write_text(json.dumps(entries, indent=1) + "\n", encoding="utf-8")
            print(f"{target}: {len(entries)} removals, derived from {args.image}")
            return 0
        proof = prove(args.image)
    except (Refused, cdp.CdpError) as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 2
    if not proof.ok:
        print(f"refused: {proof.complaint()}", file=sys.stderr)
        return 1
    print(f"{proof.image}: {len(CONFINED)} confined chords opened nothing; "
          f"{ALLOWED_CHORD[2]} still opens and the file still saves")
    print(proof.report)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
