"""What a Java practice window paints in EVERY animation frame, from before its first script until it settles.

Not a test module. `watch(image, kind)` starts one container of `image`
serving the Java practice folder (`java_session.container`), opens a headless
browser in a throwaway profile at `about:blank`, installs `RECORDER` so it runs
in the workbench's document before any of the workbench's own script, and
opens the practice. It watches for `WATCH` seconds after the workbench first
paints, reloads the page (the reader pressing reload, with the layout state
the first start stored in that browser), and watches again. It returns one
log per start: `[first start, reload]`.

⭐ **Per frame, because every defect it reads was a FLASH.** An end state read
closed each time: the Explorer painted for up to seven seconds before the
lockdown shut it, and the secondary side bar painted with a "Chat" header for
about a second and a half while the Java projects were still opening, then
went away. A reading taken once the workbench has settled sees neither.

Each log counts, over `frames` frames:
- `sidebar`: frames in which the primary side bar is laid out and visible;
- `auxiliary`: frames in which the secondary (auxiliary) side bar is;
- `chat`: frames in which any visible element is a chat view or names one:
  a part whose active view container is the chat (`workbench.panel.chat`),
  the chat's own elements, or a label or title reading "Chat". ⚠️ The part's
  title label is `display: none` at some widths, which is why the container's
  id is read and not only its words;
- `seen`: the distinct chat labels, so a refusal says what was on screen.
"""

from __future__ import annotations

import time

import java_session
from java_session import activation, cdp

#: How long each start is watched after the workbench first paints. ⚠️ Longer
#: than the lockdown's last retry (12 s), which is the latest a close -- and
#: so a part that had been open -- could land.
WATCH = 20.0

#: Runs in the workbench's document BEFORE any of its own script.
#: ⚠️ `width > 2`, since a closed part keeps a sash.
RECORDER = r"""
(function () {
  var log = window.__frames = { frames: 0, workbench: false, sidebar: 0, auxiliary: 0, chat: 0, seen: [] };
  var CHAT = /\bchat\b/i;
  var VIEWS = '.interactive-session, .interactive-input-part, .chat-input-container, .quick-chat, '
    + '.part[data-active-composite*="chat" i], .composite[id*="chat" i]';
  var NAMED = '.part .title-label, .part .title [aria-label], .part .composite-bar [aria-label], .pane-header';
  function vis(el) {
    if (!el) { return false; }
    var box = el.getBoundingClientRect(), style = getComputedStyle(el);
    return box.width > 2 && box.height > 2 && style.display !== 'none' && style.visibility !== 'hidden';
  }
  function said(el) {
    return [el.getAttribute('aria-label'), el.getAttribute('title'), el.textContent].filter(Boolean).join(' | ');
  }
  function tick() {
    log.frames += 1;
    if (document.querySelector('.monaco-workbench')) { log.workbench = true; }
    if (vis(document.querySelector('.part.sidebar'))) { log.sidebar += 1; }
    if (vis(document.querySelector('.part.auxiliarybar'))) { log.auxiliary += 1; }
    var chat = false;
    document.querySelectorAll(VIEWS).forEach(function (el) {
      if (vis(el)) {
        chat = true;
        var what = el.getAttribute('data-active-composite') || el.id || el.className;
        if (log.seen.length < 20 && log.seen.indexOf(what) < 0) { log.seen.push(what); }
      }
    });
    document.querySelectorAll(NAMED).forEach(function (el) {
      var text = said(el);
      if (CHAT.test(text) && vis(el)) {
        chat = true;
        if (log.seen.length < 20 && log.seen.indexOf(text.slice(0, 80)) < 0) { log.seen.push(text.slice(0, 80)); }
      }
    });
    if (chat) { log.chat += 1; }
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
})();
"""


def _settle(session: cdp.Session) -> dict:
    """Wait for the workbench's first paint, watch `WATCH` seconds, and return this document's log."""
    deadline = time.monotonic() + activation.HEALTH_TIMEOUT
    while not cdp.evaluate(session, "!!(window.__frames && window.__frames.workbench)"):
        if time.monotonic() > deadline:
            raise AssertionError("the workbench never painted")
        time.sleep(0.25)
    time.sleep(WATCH)
    return dict(cdp.evaluate(session, "window.__frames"))


def _still_old(session: cdp.Session) -> bool:
    """Whether the document before the reload is still the page's. A context torn down mid-read is."""
    try:
        return bool(cdp.evaluate(session, "!!window.__before_reload"))
    except cdp.CdpError:
        return True


def watch(image: str, kind: str, *mounts: str) -> list[dict]:
    """The frame logs of one Java practice window in `image`: its first start, then a reload."""
    with java_session.container(image, kind, *mounts) as (name, port), \
            java_session.browser(name, port) as opened, \
            cdp.Session(opened.page["webSocketDebuggerUrl"]) as session:
        session.call("Page.enable")
        session.call("Runtime.enable")
        session.call("Page.addScriptToEvaluateOnNewDocument", {"source": RECORDER})
        session.call("Page.navigate", {"url": opened.url})
        first = _settle(session)
        # ⛔ The old document's log must never be read as the new one's: the
        # reload is waited for by a mark only the old document carries.
        cdp.evaluate(session, "window.__before_reload = true")
        session.call("Page.reload")
        deadline = time.monotonic() + activation.HEALTH_TIMEOUT
        while _still_old(session):
            if time.monotonic() > deadline:
                raise AssertionError("the page never reloaded")
            time.sleep(0.1)
        return [first, _settle(session)]
