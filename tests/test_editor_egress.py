"""The editor makes no outbound connection of its own — read from its sockets, live.

⛔ **The reading this row started from:** a 4.137.0 image's workbench named a
newer code-server release, which it could only have learned from outside.
Measured on an idle practice session of that image, over four minutes: the
server connected to api.github.com (code-server's update check) and to
v1.telemetry.coder.com (its telemetry); the Java language server connected to
services.gradle.org; and the reader's browser queried open-vsx.org's gallery
from inside the frame. ⭐ Each is now switched off in the image, where a
consumer's compose `command:` cannot drop it: the two server flags by the
entrypoint, the gallery by `EXTENSIONS_GALLERY`, and the extensions' own by
the lockdown manifest's defaults, and Buildship's Gradle version list by a seeded
cache the entrypoint writes on every start (it honours no setting).

⭐ **The instrument is the container's own socket table**, sampled every
fraction of a second from inside its network namespace (`/proc/net/tcp`,
`tcp6`, `udp`, `udp6`), with each socket's owning process: any socket with a
remote address that is not loopback, other than a client of the served port,
is an outbound connection. A name lookup is one too — it is a UDP socket to a
resolver. ⭐ The browser's half is the page's own request log.

The static half runs everywhere. ⚠️ The container half is skipped unless
`TC_DOCKER=1`.

    TC_DOCKER=1 python3 -m unittest tests.test_editor_egress -v

⭐ **Positive control, planted on the tagged image as one derived layer:** the
entrypoint's switches and the empty gallery taken out must show outbound
connections again, or this module is blind. ⚠️ On a host with no route out the
control still fires: the lookup itself is the outbound socket.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
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
ENTRYPOINT = (ROOT / "docker" / "editor" / "entrypoint.sh").read_text(encoding="utf-8")
MANIFEST = json.loads((ROOT / "lockdown" / "package.json").read_text(encoding="utf-8"))
SWITCHES = "--disable-update-check --disable-telemetry"
#: How long a session is watched: past code-server's first update check and
#: telemetry (seconds after start) and the language server's start-up fetches.
WATCH = 150
#: The port the server listens on inside the container; a socket bound to it
#: is a client of the editor, never a connection the editor made.
SERVED = 8080
#: Every socket in the namespace, then which process holds each, repeatedly.
SAMPLER = r"""while :; do echo @@; cat /proc/net/tcp /proc/net/tcp6 /proc/net/udp /proc/net/udp6
for p in /proc/[0-9]*; do s=$(ls -l $p/fd 2>/dev/null | grep -o 'socket:\[[0-9]*\]' | tr -dc '0-9 \n' | tr '\n' ' ')
[ -n "$s" ] && echo "PID ${p#/proc/} $s"; done; sleep 0.1; done"""


def endpoint(hexed: str) -> tuple[str, int]:
    """One `/proc/net` address field, as (address, port)."""
    raw, port = hexed.split(":")
    data = bytes.fromhex(raw)
    if len(data) == 4:
        return socket.inet_ntop(socket.AF_INET, data[::-1]), int(port, 16)
    words = b"".join(data[i:i + 4][::-1] for i in range(0, 16, 4))
    return socket.inet_ntop(socket.AF_INET6, words), int(port, 16)


def loopback(address: str) -> bool:
    return address.startswith(("127.", "::ffff:127.")) or address == "::1"


def outbound(line: str) -> tuple[str, int, str] | None:
    """(remote address, remote port, socket inode) for an outbound socket line, else None."""
    fields = line.split()
    if len(fields) < 10 or not fields[0].endswith(":"):
        return None
    try:
        (_, local_port), (remote, remote_port) = endpoint(fields[1]), endpoint(fields[2])
    except ValueError:
        return None
    if remote_port == 0 or local_port == SERVED or loopback(remote):
        return None
    return remote, remote_port, fields[9]


class TheSwitchesAreInTheImage(unittest.TestCase):
    def test_the_entrypoint_appends_both_server_switches_after_any_command(self):
        self.assertTrue(ENTRYPOINT.rstrip().endswith(f'exec /usr/bin/entrypoint.sh "$@" {SWITCHES}'))

    def test_the_gallery_is_empty_by_env(self):
        self.assertIn("\nENV EXTENSIONS_GALLERY={}\n", DOCKERFILE)

    def test_buildships_version_list_is_seeded_where_it_looks_and_never_ages(self):
        self.assertIn("\nENV XDG_CACHE_HOME=/home/coder/.cache\n", DOCKERFILE)
        self.assertIn('versions="${XDG_CACHE_HOME:-${HOME:-/home/coder}/.cache}/tooling/gradle/versions.json"',
                      ENTRYPOINT)
        self.assertIn("printf '[]\\n' > \"$versions\"", ENTRYPOINT)
        self.assertIn("touch -d '2100-01-01 00:00:00' \"$versions\"", ENTRYPOINT)

    def test_the_extensions_own_call_homes_are_off_by_default(self):
        defaults = MANIFEST["contributes"]["configurationDefaults"]
        for key, value in (("redhat.telemetry.enabled", False), ("java.import.maven.offline.enabled", True),
                           ("java.import.gradle.offline.enabled", True), ("json.schemaDownload.enable", False),
                           ("npm.fetchOnlinePackageInfo", False),
                           ("typescript.disableAutomaticTypeAcquisition", True)):
            with self.subTest(key=key):
                self.assertIs(defaults[key], value)

    def test_the_parser_reads_an_outbound_socket_and_nothing_else(self):
        # 10.0.0.2:40000 -> 93.184.216.34:443 is outbound; the served port and loopback are not.
        out = "0: 0200000A:9C40 22D8B85D:01BB 01 0 0 0 1000 0 4242 1"
        served = "1: 0200000A:1F90 0100000A:9C41 01 0 0 0 1000 0 4243 1"
        local = "2: 0100007F:9C42 0100007F:1F90 01 0 0 0 1000 0 4244 1"
        self.assertEqual(outbound(out), ("93.184.216.34", 443, "4242"))
        self.assertIsNone(outbound(served))
        self.assertIsNone(outbound(local))


@unittest.skipUnless(os.environ.get("TC_DOCKER") == "1", "set TC_DOCKER=1 to build images and run containers")
class ASessionMakesNoOutboundConnection(unittest.TestCase):
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

    def _watched(self, image: str) -> dict:
        """Open a Java practice in `image`, watch it for `WATCH` s: {'sockets': [...], 'requests': [...]}."""
        found: dict[tuple[str, int], set[str]] = {}
        owners: dict[str, str] = {}
        requests: set[str] = set()
        tables = [0]
        with java_session.opened(image, "egress") as page, cdp.Session(page.page["webSocketDebuggerUrl"]) as s:
            sampler = subprocess.Popen(["docker", "exec", page.name, "sh", "-c", SAMPLER],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True)

            def read_sockets():
                for line in sampler.stdout:
                    if line.startswith("@@"):
                        tables[0] += 1
                    elif line.startswith("PID "):
                        pid, *inodes = line.split()[1:]
                        owners.update((inode, pid) for inode in inodes)
                    elif (seen := outbound(line)) is not None:
                        found.setdefault(seen[:2], set()).add(seen[2])

            def read_requests():
                while True:
                    try:
                        message = s.message()
                    except (cdp.CdpError, OSError, ValueError):
                        return
                    if message.get("method") == "Network.requestWillBeSent":
                        requests.add(message["params"]["request"]["url"].split("?")[0])

            threading.Thread(target=read_sockets, daemon=True).start()
            s.call("Network.enable")
            s.call("Page.navigate", {"url": page.url})
            threading.Thread(target=read_requests, daemon=True).start()
            time.sleep(WATCH)
            servers = java_session.language_servers(page.name)
            processes = dict(java_session.processes(page.name))
            sampler.kill()
            sampler.wait()
            sampler.stdout.close()
        named = [f"{remote}:{port} by {processes.get(int(owners.get(i, '0')), '(a process that exited)')[:90]}"
                 for (remote, port), inodes in sorted(found.items()) for i in sorted(inodes)[:1]]
        away = sorted(url for url in requests
                      if url.startswith(("http:", "https:", "ws:", "wss:"))
                      and not url.split("//", 1)[1].startswith(("127.0.0.1", "localhost", "[::1]")))
        return {"sockets": named, "requests": away, "tables": tables[0], "language_servers": len(servers)}

    def test_a_practice_session_makes_no_outbound_connection(self):
        seen = self._watched(self.tag)
        # ⭐ The instrument read something: the socket table many times over,
        # and a session that got as far as starting the Java language server.
        self.assertGreater(seen["tables"], 100, f"the socket table was hardly read: {seen}")
        self.assertGreater(seen["language_servers"], 0, f"no language server started, so its fetch was never read: {seen}")
        self.assertEqual(seen["sockets"], [], "the editor's own processes connected out")
        self.assertEqual(seen["requests"], [], "the workbench in the reader's browser requested off the host")

    def test_the_switches_planted_out_connect_out_again(self):
        image = java_session.derived(
            self.tag, "egress-plant",
            f"RUN sed -i 's/ {SWITCHES}$//' /opt/code-server/entrypoint.sh\n"
            'ENV EXTENSIONS_GALLERY=""')
        self.planted.append(image)
        seen = self._watched(image)
        self.assertNotEqual(seen["sockets"], [], f"the plant connected nowhere, so this is blind: {seen}")
        self.assertNotEqual(seen["requests"], [], f"the plant's browser requested nothing off the host: {seen}")

    def test_the_gradle_list_seed_planted_out_lets_the_language_server_connect_out(self):
        """⭐ Set empty, Buildship looks for its list where the seed is not, and fetches it."""
        image = java_session.derived(self.tag, "egress-plant", 'ENV XDG_CACHE_HOME=""')
        self.planted.append(image)
        seen = self._watched(image)
        # ⚠️ The server's own switches are intact in this plant, so what connects
        # out is the language server; a socket that short-lived can close before
        # its owner is read, so the address is asserted, not the owner.
        self.assertNotEqual(seen["sockets"], [], f"the plant connected nowhere, so this is blind: {seen}")
        self.assertTrue(all(entry.split(" by ")[0].endswith(":443") for entry in seen["sockets"]), seen)


if __name__ == "__main__":
    unittest.main()
