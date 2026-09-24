"""A closed practice session is released within the grace, and a drop inside it still reconnects.

⛔ **The reading this row started from:** every closed practice window left its
extension host and its Java language server running, about 1.1 GiB each, until
the server's reconnection grace ended -- upstream's three hours. ⭐ The image
now sets the grace (`docker/editor/Dockerfile`, `CODE_SERVER_RECONNECTION_GRACE_TIME`).

⚠️ **Which close this reads, measured:** a tab the browser closes cleanly, or a
page that navigates away, tells the server it is leaving, and the server
disposes the session at once; only a session that ends WITHOUT saying so is
held for the grace. So the worst case is read here -- the browser killed
outright, as a crash, a killed process or a machine that sleeps would -- over
repeated sessions on one server.

⭐ **The other half is why the grace is not zero:** a connection that drops and
comes back inside the grace must reconnect to the SAME extension host, not
lose the reader's window. The drop is made in the page: every WebSocket the
workbench holds is closed, and new ones are refused for a while, which is a
network gone and back from the workbench's point of view.

The static half runs everywhere. ⚠️ The container half is skipped unless
`TC_DOCKER=1`; it takes several minutes, because it waits the grace out.

    TC_DOCKER=1 python3 -m unittest tests.test_editor_idle -v

⭐ **Two positive controls, planted on the tagged image as one derived layer:**
the upstream grace put back must still hold a closed session after the bound,
and a grace shorter than the drop must refuse the reconnection.
"""

from __future__ import annotations

import os
import re
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docker" / "editor"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cdp  # noqa: E402
import editor_plan  # noqa: E402
import java_session  # noqa: E402

BUILD = ROOT / "docker" / "editor" / "build.py"
SET = "java,maven"
DOCKERFILE = (ROOT / editor_plan.DOCKERFILE).read_text(encoding="utf-8")
GRACE_LINE = re.compile(r"(?m)^ENV CODE_SERVER_RECONNECTION_GRACE_TIME=(\d+)$")
#: How long after the grace a closed session may take to be gone: the server's
#: own sweep, and this module's polling interval.
MARGIN = 60
#: A hidden tab's timers run once a minute, and the protocol gives up on a
#: silent peer after 20 s, so a grace under this would lose a hidden tab.
FLOOR = 90
SESSIONS = 3
#: How long the drop lasts: longer than a hidden tab's throttled minute.
DROP = 60
#: A grace shorter than the drop, for the control that must fail to reconnect.
SHORT = 15
LOGS = "/home/coder/.local/share/code-server/logs"
RECONNECTED = "[ExtensionHostConnection] The client has reconnected."

#: Installed before the workbench's first script: tracks every WebSocket it
#: opens, and while `__blocked` is set points new ones at a closed port.
SOCKETS = r"""(() => {
  const Native = window.WebSocket, all = window.__sockets = [];
  window.__blocked = false;
  function Tracked(url, protocols) {
    const target = window.__blocked ? 'ws://127.0.0.1:9/' : url;
    const ws = protocols === undefined ? new Native(target) : new Native(target, protocols);
    all.push(ws);
    return ws;
  }
  Tracked.prototype = Native.prototype;
  for (const k of ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED']) { Tracked[k] = Native[k]; }
  window.WebSocket = Tracked;
})();"""
CUT = """(() => { window.__blocked = true; let n = 0;
  for (const ws of window.__sockets) { if (ws.readyState === 1) { ws.close(); n += 1; } } return n; })()"""


def grace() -> int:
    found = GRACE_LINE.findall(DOCKERFILE)
    return int(found[0]) if len(found) == 1 else -1


class TheGraceIsSet(unittest.TestCase):
    def test_the_image_sets_one_grace_in_minutes_not_hours(self):
        self.assertGreaterEqual(grace(), FLOOR, "one ENV line, long enough for a hidden tab to reconnect")
        self.assertLessEqual(grace(), 600, "a closed session is released in minutes")

    def test_it_is_an_env_so_a_consumer_command_does_not_drop_it(self):
        self.assertNotIn("reconnection-grace-time", DOCKERFILE.split("\nCMD ", 1)[1])


@unittest.skipUnless(os.environ.get("TC_DOCKER") == "1", "set TC_DOCKER=1 to build images and run containers")
class ASessionIsReleasedAndReconnects(unittest.TestCase):
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

    def _plant(self, value: str) -> str:
        image = java_session.derived(self.tag, "idle-plant", f"ENV CODE_SERVER_RECONNECTION_GRACE_TIME={value}")
        self.planted.append(image)
        return image

    def _running(self, name: str, hosts: set) -> int:
        """Wait for the NEW extension host a just-opened window starts, and its language server."""
        deadline = time.monotonic() + java_session.activation.ACTIVATION_TIMEOUT
        while True:
            running = java_session.extension_hosts(name)
            new = [pid for pid in running if pid not in hosts]
            earlier = [pid for pid in running if pid in hosts]
            if new and len(java_session.language_servers(name)) > len(earlier):
                return new[0]
            self.assertLess(time.monotonic(), deadline, "the session never started its extension host")
            time.sleep(3)

    def _killed_sessions(self, count: int, name: str, port: int, scratch: Path) -> dict[int, float]:
        """`count` sessions, one after another, each ended by killing its browser outright.

        Returns {extension host: when its browser was killed}. ⭐ Each host is
        read ALIVE just after its kill, so what follows is the grace and not a
        clean close.
        """
        killed: dict[int, float] = {}
        for number in range(count):
            with java_session.browser(name, port, scratch / f"profile-{number}") as page:
                with cdp.Session(page.page["webSocketDebuggerUrl"]) as s:
                    s.call("Page.navigate", {"url": page.url})
                    host = self._running(name, set(killed))
                    time.sleep(10)  # the language server is up before the window goes
                page.browser.kill()
                page.browser.wait()
                killed[host] = time.monotonic()
            time.sleep(5)
            self.assertIn(host, java_session.extension_hosts(name), "a killed session was released at once")
        return killed

    def _released(self, name: str, killed: dict[int, float], bound: float) -> dict[int, float | None]:
        """{host: seconds from its kill until it was gone, or None if it outlived `bound`}."""
        gone: dict[int, float | None] = {}
        while len(gone) < len(killed):
            now, running = time.monotonic(), set(java_session.extension_hosts(name))
            for host, at in killed.items():
                if host not in gone and host not in running:
                    gone[host] = now - at
                elif host not in gone and now - at > bound:
                    gone[host] = None
            time.sleep(5)
        return gone

    def test_closed_sessions_are_released_within_the_grace(self):
        with java_session.container(self.tag, "idle") as (name, port, scratch):
            killed = self._killed_sessions(SESSIONS, name, port, scratch)
            gone = self._released(name, killed, grace() + MARGIN)
            time.sleep(10)
            servers = java_session.language_servers(name)
        self.assertEqual([host for host, took in gone.items() if took is None], [],
                         f"held past the grace and its margin: {gone}")
        self.assertEqual(servers, [], "a language server outlived its extension host")

    def test_the_upstream_grace_planted_back_still_holds_a_closed_session(self):
        image = self._plant("")
        with java_session.container(image, "idle-plant") as (name, port, scratch):
            killed = self._killed_sessions(1, name, port, scratch)
            gone = self._released(name, killed, grace() + MARGIN)
        self.assertEqual(list(gone.values()), [None], f"the plant released the session, so this is blind: {gone}")

    def _dropped(self, image: str) -> dict:
        """Open a session, cut its connections for `DROP` seconds, and read what came back."""
        with java_session.opened(image, "drop") as page, cdp.Session(page.page["webSocketDebuggerUrl"]) as s:
            s.call("Page.enable")
            s.call("Runtime.enable")
            s.call("Page.addScriptToEvaluateOnNewDocument", {"source": SOCKETS})
            s.call("Page.navigate", {"url": page.url})
            host = self._running(page.name, set())
            time.sleep(10)
            cut = cdp.evaluate(s, CUT)
            time.sleep(DROP)
            cdp.evaluate(s, "window.__blocked = false")
            deadline, text, log = time.monotonic() + 90, "", ""
            while time.monotonic() < deadline:
                text = cdp.evaluate(s, "document.body.innerText")
                log = java_session.run(["docker", "exec", page.name, "sh", "-c",
                                        f"cat {LOGS}/*/remoteagent.log"]).stdout
                if RECONNECTED in log or "Cannot reconnect" in text:
                    break
                time.sleep(3)
            return {"cut": cut, "host": host, "hosts": java_session.extension_hosts(page.name),
                    "reconnected": RECONNECTED in log, "refused": "Cannot reconnect" in text}

    def test_a_drop_inside_the_grace_reconnects_to_the_same_extension_host(self):
        seen = self._dropped(self.tag)
        self.assertGreater(seen["cut"], 0, f"no connection was cut, so nothing was read: {seen}")
        self.assertTrue(seen["reconnected"], seen)
        self.assertFalse(seen["refused"], seen)
        self.assertEqual(seen["hosts"], [seen["host"]], seen)

    def test_a_grace_shorter_than_the_drop_planted_refuses_the_reconnection(self):
        seen = self._dropped(self._plant(str(SHORT)))
        self.assertGreater(seen["cut"], 0, f"no connection was cut, so nothing was read: {seen}")
        self.assertTrue(seen["refused"], f"the plant reconnected, so this is blind: {seen}")
        self.assertFalse(seen["reconnected"], seen)


if __name__ == "__main__":
    unittest.main()
