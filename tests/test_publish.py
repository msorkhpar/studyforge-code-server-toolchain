"""The publish step names the registry namespace from the environment only, and pushes only when asked.

Run from the component root: `python3 -m unittest tests.test_publish -v`.

⭐ **What is held, with no Docker.** With `TOOLCHAIN_NAMESPACE` unset or empty the
script refuses before it plans anything and runs nothing. A dry run prints the
exact commands, in order, and runs none. The image name is the namespace plus
the tag the build itself computes, never a hand-written one. `docker push` is
printed only with `--push`, and `docker login` is never printed. ⛔ No tracked
file carries a registry namespace literal, and the value the caller's own
environment holds for the variable (when it holds one) is in no tracked file.

Standard library only, plus `git`.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docker"))

import publish  # noqa: E402

VARIABLE = "TOOLCHAIN_NAMESPACE"
#: An obviously fake namespace: tests never use a real one.
PLACEHOLDER = "example-namespace"
SET = ["--runtimes", "java,maven"]


def publish_main(argv, env):
    """`(exit code, printed stdout, stderr, docker/other commands actually run)`."""
    ran, out, err = [], io.StringIO(), io.StringIO()
    with mock.patch.object(sys, "stderr", err):
        code = publish.main(argv, env=env, run=lambda command, **kw: ran.append(command) or mock.Mock(returncode=0),
                            out=out)
    return code, out.getvalue(), err.getvalue(), ran


def tag_of(script: str) -> str:
    done = subprocess.run([sys.executable, str(ROOT / script), *SET, "--print-tag"], capture_output=True, text=True,
                          check=True, cwd=ROOT)
    return done.stdout.strip().rsplit(":", 1)[1]


class Refuses(unittest.TestCase):
    def test_an_unset_or_empty_namespace_refuses_and_runs_nothing(self):
        for env in ({}, {VARIABLE: ""}, {VARIABLE: "   "}):
            for argv in (["editor", *SET], ["runner", *SET, "--dry-run"], ["runner", *SET, "--push"]):
                with self.subTest(env=env, argv=argv):
                    code, printed, err, ran = publish_main(argv, env)
                    self.assertEqual(code, 2)
                    self.assertIn(VARIABLE, err)
                    self.assertEqual((printed, ran), ("", []))

    def test_a_value_that_is_not_a_namespace_refuses(self):
        code, printed, err, ran = publish_main(["runner", *SET], {VARIABLE: "Bad Name; rm -rf"})
        self.assertEqual((code, printed, ran), (2, "", []))
        self.assertIn("not a registry namespace", err)

    def test_there_is_no_flag_that_names_a_namespace(self):
        with self.assertRaises(SystemExit), mock.patch.object(sys, "stderr", io.StringIO()):
            publish.main(["runner", *SET, "--namespace", PLACEHOLDER], env={})


class DryRun(unittest.TestCase):
    def test_it_prints_the_build_and_the_tag_and_runs_no_docker(self):
        for image, script in (("runner", "docker/minimal/build.py"), ("editor", "docker/editor/build.py")):
            with self.subTest(image=image):
                code, printed, err, ran = publish_main([image, *SET, "--dry-run"], {VARIABLE: PLACEHOLDER})
                tag = tag_of(script)
                self.assertEqual(code, 0, err)
                self.assertEqual(ran, [], "a dry run started a process")
                self.assertEqual(printed.splitlines(), [
                    f"python3 {script} --runtimes java,maven",
                    f"docker tag code-server-toolchain/{image}:{tag} {PLACEHOLDER}/{publish.PUBLISHED[image]}:{tag}"])

    def test_push_is_printed_only_when_asked(self):
        env = {VARIABLE: PLACEHOLDER}
        plain = publish_main(["runner", *SET, "--dry-run"], env)[1]
        pushed = publish_main(["runner", *SET, "--dry-run", "--push"], env)[1]
        self.assertNotIn("docker push", plain)
        self.assertEqual(pushed.splitlines()[-1], f"docker push {PLACEHOLDER}/studyforge-code-toolchain-runner:{tag_of('docker/minimal/build.py')}")

    def test_a_dry_run_from_the_command_line_needs_no_docker_on_the_path(self):
        done = subprocess.run([sys.executable, str(ROOT / "docker" / "publish.py"), "runner", *SET, "--dry-run"],
                              capture_output=True, text=True, cwd=ROOT,
                              env={"PATH": "/nonexistent", VARIABLE: PLACEHOLDER})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f"{PLACEHOLDER}/studyforge-code-toolchain-runner:", done.stdout)
        self.assertNotIn(f"{PLACEHOLDER}/runner:", done.stdout)


class PublishedNames(unittest.TestCase):
    """A registry sees `studyforge-code-toolchain-<image>`; the local build names are not touched."""

    NAMES = {"runner": "studyforge-code-toolchain-runner", "editor": "studyforge-code-toolchain-editor"}

    def test_the_published_names_are_the_prefixed_ones(self):
        self.assertEqual(publish.PUBLISHED, self.NAMES)

    def test_a_dry_run_publishes_under_the_prefixed_name_and_keeps_the_local_one(self):
        for image, name in self.NAMES.items():
            with self.subTest(image=image):
                printed = publish_main([image, *SET, "--dry-run", "--push"], {VARIABLE: PLACEHOLDER})[1].splitlines()
                tag_line = printed[1].split()
                self.assertTrue(tag_line[2].startswith(f"code-server-toolchain/{image}:"), tag_line)
                self.assertTrue(tag_line[3].startswith(f"{PLACEHOLDER}/{name}:"), tag_line)
                self.assertTrue(printed[2].startswith(f"docker push {PLACEHOLDER}/{name}:"), printed[2])

    def test_the_contract_states_the_published_names(self):
        import json
        contract = json.loads((ROOT / "consuming.json").read_text(encoding="utf-8"))
        for image, name in self.NAMES.items():
            registry = contract[image]["image"]["registry"]
            self.assertEqual(registry["published_name"], name)
            self.assertEqual(registry["reference"], "${TOOLCHAIN_NAMESPACE}/" + name + ":<tag>")


class RealRun(unittest.TestCase):
    def test_it_builds_then_tags_and_pushes_only_with_the_flag_and_never_logs_in(self):
        env = {VARIABLE: PLACEHOLDER}
        _, _, _, without = publish_main(["runner", *SET], env)
        _, _, _, withit = publish_main(["runner", *SET, "--push"], env)
        self.assertEqual([c[:2] for c in without], [["python3", "docker/minimal/build.py"], ["docker", "tag"]])
        self.assertEqual([c[:2] for c in withit][-1], ["docker", "push"])
        self.assertFalse([c for c in without + withit if "login" in c])

    def test_a_failing_build_stops_before_it_tags(self):
        ran = []
        run = lambda command, **kw: ran.append(command) or mock.Mock(returncode=1)  # noqa: E731
        code = publish.main(["runner", *SET, "--push"], env={VARIABLE: PLACEHOLDER}, run=run, out=io.StringIO())
        self.assertEqual((code, len(ran)), (1, 1))


class NoLiteral(unittest.TestCase):
    """The namespace is a variable's name in every tracked file, never a value."""

    @staticmethod
    def texts():
        listed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True)
        for name in sorted(n for n in listed.stdout.split("\0") if n and n not in ("pins.json", "editor-pins.json")):
            try:
                yield name, (ROOT / name).read_text(encoding="utf-8")
            except (UnicodeDecodeError, FileNotFoundError):
                continue

    def test_no_tracked_file_names_a_registry_namespace_or_a_login(self):
        hub = re.compile(r"(?:docker\.io|index\.docker\.io)/[\w.-]+/")
        push = re.compile(r"docker push\s+(?![<$]|remote\b)\S+")
        login = re.compile(r"docker login\b.*(?:-u\b|--username)")
        found = [f"{name}:{number}" for name, text in self.texts() if name != "tests/test_publish.py"
                 for number, line in enumerate(text.splitlines(), 1)
                 if hub.search(line) or push.search(line) or login.search(line)]
        self.assertEqual(found, [])

    def test_the_callers_own_namespace_is_in_no_tracked_file(self):
        value = os.environ.get(VARIABLE, "").strip()
        if not value:
            self.skipTest(f"{VARIABLE} is not set here, so there is no value to look for")
        self.assertEqual([name for name, text in self.texts() if value in text], [])

    def test_the_sweep_can_fire(self):
        line = "docker push someone/editor:tag"
        self.assertTrue(re.search(r"docker push\s+(?![<$]|remote\b)\S+", line))
        self.assertFalse(re.search(r"docker push\s+(?![<$]|remote\b)\S+", "docker push <namespace>/editor:<tag>"))


if __name__ == "__main__":
    unittest.main()
