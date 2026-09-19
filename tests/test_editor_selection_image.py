"""The editor's toolchain SELECTION (TC-02), built and run for real — both ways.

⛔ Skipped unless `TC_DOCKER=1`: it builds images and starts containers. Run it
as ONE container job (the whole module under whatever lock the host uses):

    TC_DOCKER=1 python3 -m unittest tests.test_editor_selection_image -v

It builds three sets: `java,maven` (the Java corpus's), `python` (a set with no
java) and the default five, and reads each clause off the images. Every
container runs with `--network none` and publishes no port. Plants go into
temporary copies under `.work/` (git-ignored), and every image, container and
volume this module creates is removed afterwards — the three real images too,
unless `TC_KEEP_IMAGES=1`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docker" / "editor"))

import editor_plan  # noqa: E402

BUILD = ROOT / "docker" / "editor" / "build.py"
WORK = ROOT / ".work" / "tests-editor-selection"
PINS = editor_plan.runner_plan.load(ROOT)
EPINS = editor_plan.load(ROOT)
EXTENSIONS_DIR = "/opt/code-server/extensions"
SHELLS = (["sh", "-c"], ["bash", "-lc"], ["bash", "-ic"])
JAVA_MAVEN, PYTHON = ("java", "maven"), ("python",)
#: code-server's own node answers the health check: a set without python has no python3.
HEALTH = ("/usr/lib/code-server/lib/node", "-e",
          "fetch('http://127.0.0.1:8080/healthz').then(r => console.log(r.status), () => console.log(0))")


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, **kwargs)


def build(names, root: Path = ROOT) -> subprocess.CompletedProcess:
    return run([sys.executable, str(BUILD), "--root", str(root), "--runtimes", ",".join(names)])


def tag(names, root: Path = ROOT) -> str:
    return run([sys.executable, str(BUILD), "--root", str(root), "--runtimes", ",".join(names),
                "--print-tag"]).stdout.strip()


def planted_copy(name: str, old: str, new: str) -> Path:
    """A copy of the build's inputs with one Dockerfile defect planted, never touching the tree."""
    target = WORK / name
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    for file in ("pins.json", "editor-pins.json", ".dockerignore"):
        shutil.copy(ROOT / file, target / file)
    shutil.copytree(ROOT / "docker", target / "docker", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "prime", target / "prime", ignore=shutil.ignore_patterns("__pycache__"))
    path = target / editor_plan.DOCKERFILE
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    path.write_text(text.replace(old, new), encoding="utf-8")
    return target


@unittest.skipUnless(os.environ.get("TC_DOCKER") == "1", "set TC_DOCKER=1 to build and run the images")
class TheSelectedImages(unittest.TestCase):
    containers: list[str] = []
    planted: list[str] = []
    images: dict[tuple[str, ...], str] = {}
    running: dict[tuple[str, ...], str] = {}

    @classmethod
    def setUpClass(cls):
        for names in (JAVA_MAVEN, PYTHON, editor_plan.DEFAULT_SET):
            built = build(names)
            if built.returncode != 0:
                raise AssertionError(f"the {names} editor did not build:\n{built.stderr[-3000:]}")
            cls.images[names] = tag(names)
        for names in (JAVA_MAVEN, PYTHON):
            cls.running[names] = cls.start(cls.images[names])
        for container in cls.running.values():
            cls.wait_healthy(container)

    @classmethod
    def tearDownClass(cls):
        for name in cls.containers:
            run(["docker", "rm", "-f", name])
        images = list(cls.planted)
        if os.environ.get("TC_KEEP_IMAGES") != "1":
            images += list(cls.images.values())
        for image in images:
            run(["docker", "image", "rm", "-f", image])
        shutil.rmtree(WORK, ignore_errors=True)

    @classmethod
    def start(cls, image: str) -> str:
        name = f"tc02-editor-{uuid.uuid4().hex[:8]}"
        cls.containers.append(name)
        started = run(["docker", "run", "-d", "--name", name, "--network", "none", image])
        assert started.returncode == 0, started.stderr
        return name

    @staticmethod
    def exec(container: str, *command: str) -> subprocess.CompletedProcess:
        return run(["docker", "exec", container, *command])

    @classmethod
    def wait_healthy(cls, container: str, seconds: int = 60) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if cls.exec(container, *HEALTH).stdout.strip() == "200":
                return True
            time.sleep(1)
        return False

    @staticmethod
    def inspect(image: str) -> dict:
        return json.loads(run(["docker", "image", "inspect", image]).stdout)[0]

    def planted_build_fails(self, root: Path, names, needle: str) -> None:
        self.planted.append(tag(names, root))
        built = build(names, root)
        self.assertNotEqual(built.returncode, 0, "the planted build succeeded")
        self.assertIn(needle, built.stdout + built.stderr)

    def installed(self, names) -> list[str]:
        listed = self.exec(self.running[names], "code-server", "--extensions-dir", EXTENSIONS_DIR,
                           "--list-extensions", "--show-versions")
        return sorted(line.strip() for line in listed.stdout.splitlines() if "@" in line)

    def seed(self, names) -> dict:
        text = self.exec(self.running[names], "cat", "/opt/code-server/seed/settings.json").stdout
        return json.loads(re.sub(r"^\s*//.*$", "", text, flags=re.M))

    # ------------------------------------------------------- java + maven
    def test_the_java_maven_editor_works_and_reports_its_pinned_versions_in_every_shell(self):
        container = self.running[JAVA_MAVEN]
        self.assertEqual(self.exec(container, *HEALTH).stdout.strip(), "200")
        for shell in SHELLS:
            for name in JAVA_MAVEN:
                for check in PINS["runtimes"][name]["checks"]:
                    with self.subTest(shell=" ".join(shell), runtime=name):
                        found = self.exec(container, *shell, check["command"])
                        self.assertEqual(found.returncode, 0, found.stdout + found.stderr)
                        expect = check["expect"].format(version=PINS["runtimes"][name]["version"])
                        self.assertIn(expect, found.stdout + found.stderr)

    def test_the_java_maven_editor_is_measurably_smaller_than_the_full_one(self):
        small = self.inspect(self.images[JAVA_MAVEN])["Size"]
        full = self.inspect(self.images[editor_plan.DEFAULT_SET])["Size"]
        print(f"\nsizes: java,maven {small} bytes; default set {full} bytes", file=sys.stderr)
        self.assertLess(small, full * 0.9)

    def test_each_image_recorded_the_version_of_exactly_its_selected_toolchains_at_build_time(self):
        for names in (JAVA_MAVEN, PYTHON, editor_plan.DEFAULT_SET):
            with self.subTest(names=names):
                image = self.images[names]
                recorded = run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "cat", image,
                                "/opt/code-server/toolchain-versions"]).stdout.splitlines()
                expected = set(names) | ({"typescript"} if "node" in names else set())
                for shell in ("sh -c", "bash -lc"):
                    reported = {line.split(": ")[1] for line in recorded if line.startswith(shell + ": ")}
                    self.assertEqual(reported, expected)

    def test_an_unselected_toolchain_is_absent_in_every_shell(self):
        for names, absent in ((JAVA_MAVEN, ("gradle", "kotlinc", "node", "tsc", "/usr/local/bin/python3")),
                              (PYTHON, ("java", "mvn", "gradle", "kotlinc", "node", "tsc"))):
            for shell in SHELLS:
                for command in absent:
                    with self.subTest(names=names, shell=" ".join(shell), command=command):
                        found = self.exec(self.running[names], *shell, f"command -v {command}")
                        self.assertNotEqual(found.returncode, 0, found.stdout)
        self.assertEqual(self.exec(self.running[PYTHON], "python3", "--version").returncode, 0)

    # --------------------------------------------- JAVA_HOME and PATH (TC-01/16)
    def test_java_home_is_set_exactly_when_java_is_selected_in_every_shell(self):
        for names, want in ((JAVA_MAVEN, editor_plan.JAVA_HOME), (PYTHON, "unset")):
            for shell in SHELLS:
                with self.subTest(names=names, shell=" ".join(shell)):
                    found = self.exec(self.running[names], *shell, 'printf %s "${JAVA_HOME-unset}"')
                    self.assertEqual(found.stdout, want)
        self.assertNotIn("JAVA_HOME", " ".join(self.inspect(self.images[PYTHON])["Config"]["Env"]))

    def test_every_opt_path_entry_names_a_selected_runtime_in_every_shell(self):
        for names in (JAVA_MAVEN, PYTHON):
            want = [path for name, path in editor_plan.PATH_DIRS if name in names]
            for shell in SHELLS:
                with self.subTest(names=names, shell=" ".join(shell)):
                    path = self.exec(self.running[names], *shell, 'printf %s "$PATH"').stdout.split(":")
                    self.assertEqual(list(dict.fromkeys(p for p in path if p.startswith("/opt/"))), want)

    def test_a_set_without_java_that_carries_java_home_is_refused_at_build(self):
        root = planted_copy("java-home-without-java", "FROM ${EDITOR_BASE} AS home-java-no",
                            "FROM home-java-yes AS home-java-no")
        self.planted_build_fails(root, PYTHON, "JAVA_HOME is '/opt/java/openjdk' under sh -c")

    def test_a_path_entry_for_an_unselected_runtime_is_refused_at_build(self):
        root = planted_copy("path-without-java", "ENV PATH=${EDITOR_PATH}",
                            "ENV PATH=/opt/java/openjdk/bin:${EDITOR_PATH}")
        self.planted_build_fails(root, PYTHON, "PATH names /opt/java/openjdk/bin under sh -c")

    # ------------------------------------------------ extensions and the seed
    def test_each_image_installs_exactly_the_extensions_for_its_runtimes(self):
        for names in (JAVA_MAVEN, PYTHON):
            with self.subTest(names=names):
                want = sorted(f"{e}@{v['version']}" for e, v in EPINS["extensions"].items() if v["for"] in names)
                self.assertEqual(self.installed(names), want)
                self.assertTrue(want)

    def test_the_seed_carries_settings_only_for_the_selected_runtimes(self):
        for names, kept, dropped in ((JAVA_MAVEN, "java.", "python."), (PYTHON, "python.", "java.")):
            with self.subTest(names=names):
                keys = set(self.seed(names))
                self.assertTrue(any(k.startswith(kept) for k in keys))
                self.assertFalse(any(k.startswith(dropped) for k in keys))
        runtime = self.seed(JAVA_MAVEN)["java.configuration.runtimes"][0]["name"]
        self.assertEqual(runtime, editor_plan.java_runtime(PINS))

    def test_each_image_declares_its_set(self):
        for names, image in self.images.items():
            with self.subTest(names=names):
                labels = self.inspect(image)["Config"]["Labels"]
                self.assertEqual(labels["org.studyforge.editor.runtimes"], " ".join(names))


if __name__ == "__main__":
    unittest.main()
