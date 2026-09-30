"""A probe hands the engine no host path, honours the caller's context, and keeps the browser's words.

Run from the component root: `python3 -m unittest tests.test_engine -v`. No
Docker and no browser: a recording `docker` and a scripted browser stand in on
`PATH`, so each reading is of what the probe ASKS for.

⛔ **Every docker step runs on any engine,
Windows included.** Docker Desktop refuses a bind of a host `/tmp` directory,
and Windows has none, so the probe folder crosses as a tar stream into a named
volume. ⛔ `DOCKER_CONTEXT` is the caller's: it must reach every `docker` the
probes run, and nothing may name or switch a context. ⛔ A browser that dies
(with a long `TMPDIR`, Chrome's singleton socket does not fit and it exits
before opening a page) must be QUOTED by the refusal, never read as "activated
in no session".
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docker" / "editor"))

import activation  # noqa: E402
import engine  # noqa: E402

_spec = importlib.util.spec_from_file_location("runner_build_for_engine", ROOT / "docker" / "minimal" / "build.py")
runner_build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner_build)

FAKE_DOCKER = """#!{python}
import json, os, sys
args = sys.argv[1:]
record = {{"args": args, "context": os.environ.get("DOCKER_CONTEXT")}}
if "-i" in args:
    data = sys.stdin.buffer.read()
    open({stdin!r}, "wb").write(data)
    record["stdin"] = len(data)
with open({log!r}, "a") as out:
    out.write(json.dumps(record) + "\\n")
if args[:2] == ["image", "inspect"]:
    print(json.dumps(["--bind-addr", "0.0.0.0:8080", "."]) if "--format" in args else "[]")
"""

FAKE_BROWSER = """#!/bin/sh
echo "TMPDIR=$TMPDIR"
echo "[0926/120000.000000:ERROR:process_singleton_posix.cc(1)] Socket path too long: $TMPDIR/.x/SingletonSocket" >&2
exit 1
"""


def executable(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class Recorded(unittest.TestCase):
    """A recording `docker` first on `PATH`, and `DOCKER_CONTEXT` set to a name no engine has."""

    CONTEXT = "a-context-the-caller-chose"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="engine-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        self.log, self.stdin = self.tmp / "docker.log", self.tmp / "stdin.tar"
        executable(bin_dir / "docker", FAKE_DOCKER.format(python=sys.executable, log=str(self.log),
                                                          stdin=str(self.stdin)))
        patched = mock.patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                                               "DOCKER_CONTEXT": self.CONTEXT})
        patched.start()
        self.addCleanup(patched.stop)

    def calls(self) -> list[dict]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]


class TheProbeFolderIsAVolumeTheEngineOwns(Recorded):

    def test_seed_and_start_hand_the_engine_no_host_path(self):
        engine.seed("an-image", "probe-vol", {"probe.txt": "text\n", ".vscode/settings.json": "{}"})
        engine.start("an-image", "probe-1", "probe-vol")
        engine.remove("probe-1", "probe-vol")
        calls = self.calls()
        self.assertTrue(calls, "the recording docker was never called")
        for call in calls:
            args = call["args"]
            for flag, value in zip(args, args[1:]):
                if flag in ("-v", "--volume"):
                    source = value.split(":", 1)[0]
                    self.assertNotIn("/", source, f"a host path handed to the engine: {args}")
                    self.assertNotIn("\\", source, f"a host path handed to the engine: {args}")
                    self.assertFalse(Path(source).is_absolute(), f"a host path handed to the engine: {args}")
                self.assertNotEqual(flag, "--mount", f"a bind by another spelling: {args}")
        run = next(call["args"] for call in calls if call["args"][:2] == ["run", "-d"])
        self.assertIn(f"probe-vol:{engine.SOURCES}", run)
        self.assertEqual(["volume", "rm", "-f", "probe-vol"], calls[-1]["args"])

    def test_the_seed_crosses_on_stdin_owned_by_the_probe_user(self):
        engine.seed("an-image", "probe-vol", {"probe.txt": "text\n", ".vscode/settings.json": "{}"})
        with tarfile.open(fileobj=io.BytesIO(self.stdin.read_bytes())) as archive:
            members = {member.name: member for member in archive.getmembers()}
            self.assertEqual(archive.extractfile(members["probe.txt"]).read(), b"text\n")
        self.assertIn(".vscode", members)
        self.assertTrue(members[".vscode"].isdir())
        uid, gid = (int(part) for part in engine.host_user().split(":"))
        for member in members.values():
            self.assertEqual((member.uid, member.gid), (uid, gid), member.name)

    def test_a_host_without_uids_runs_as_the_images_coder(self):
        with mock.patch.object(engine.os, "getuid", None, create=True), \
                mock.patch.object(engine.os, "getgid", None, create=True):
            self.assertEqual(engine.host_user(), "1000:1000")


class TheCallersContextReachesEveryDocker(Recorded):

    def test_every_probe_call_carries_the_callers_context_and_names_none(self):
        engine.seed("an-image", "v", {"a": "b"})
        engine.start("an-image", "n", "v")
        activation.exthost_log("n", SimpleNamespace(id="x.y", record="r.log"))
        engine.remove("n", "v")
        runner_build.image_present("an-image")
        calls = self.calls()
        self.assertGreaterEqual(len(calls), 6, calls)
        for call in calls:
            self.assertEqual(call["context"], self.CONTEXT, f"the caller's DOCKER_CONTEXT was dropped: {call}")
            self.assertNotIn("--context", call["args"])
            self.assertNotEqual(call["args"][:2], ["context", "use"])

    def test_no_source_switches_or_names_a_context(self):
        for path in sorted(ROOT.rglob("*")):
            parts = path.relative_to(ROOT).parts
            if not path.is_file() or path.suffix not in {".py", ".sh"} or {"tests", ".git", ".work"} & set(parts):
                continue
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertNotIn("context use", text)
                self.assertNotIn('"--context"', text)


class TheBrowsersWordsAreKept(Recorded):

    def setUp(self):
        super().setUp()
        self.browser = executable(self.tmp / "bin" / "fake-browser", FAKE_BROWSER)

    def test_a_dead_browser_is_quoted_not_read_as_no_session(self):
        lock = SimpleNamespace(id="studyforge.practice-focus", record="r.log", banner="a banner")
        with mock.patch.object(activation, "ACTIVATION_TIMEOUT", 30.0):
            proof = activation._drive(str(self.browser), "an-image", "n", 1, lock)
        self.assertFalse(proof.ok)
        self.assertIn("Socket path too long", proof.complaint())
        self.assertIn("Socket path too long", proof.browser)

    def test_the_browser_runs_under_a_short_tmpdir_whatever_it_inherited(self):
        deep = self.tmp / ("d" * 60) / ("e" * 60)
        deep.mkdir(parents=True)
        with mock.patch.dict(os.environ, {"TMPDIR": str(deep)}), mock.patch.object(tempfile, "tempdir", None):
            with engine.Browser(str(self.browser), "about:blank") as session:
                session.process.wait(timeout=20)
                said = session.tail()
        tmpdir = next(line for line in said.splitlines() if line.startswith("TMPDIR="))[len("TMPDIR="):]
        self.assertLessEqual(len(tmpdir), engine.SHORT_BASE + 20, tmpdir)
        self.assertLess(len(tmpdir) + len("/.com.google.Chrome.XXXXXX/SingletonSocket"), 108, tmpdir)

    def test_the_browsers_home_is_removed_afterwards(self):
        with engine.Browser(str(self.browser), "about:blank") as session:
            home = session.home
            session.process.wait(timeout=20)
        self.assertFalse(home.exists())


if __name__ == "__main__":
    unittest.main()
