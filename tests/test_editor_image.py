"""The editor image, built and run for real — every assertion BOTH ways.

⛔ Skipped unless `TC_DOCKER=1`: it builds images and starts containers. Run
it as ONE container job (the whole module under whatever lock the host uses):

    TC_DOCKER=1 python3 -m unittest tests.test_editor_image -v

Every container runs with `--network none` and publishes no port; the editor's
run shape is TC-05's. Plants go into temporary copies under `.work/`
(git-ignored), and every image, container and volume this module creates is
removed afterwards — the real editor image too, unless `TC_KEEP_IMAGES=1`.
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

runner_plan = editor_plan.runner_plan
BUILD = ROOT / "docker" / "editor" / "build.py"
WORK = ROOT / ".work" / "tests-editor"
PINS = runner_plan.load(ROOT)
EPINS = editor_plan.load(ROOT)
#: The lockdown extension every image installs, whatever its set (TC-04).
LOCKDOWN = editor_plan.lockdown_identity(ROOT)
EXTENSIONS_DIR = "/opt/code-server/extensions"
BASE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
#: One version check per declared runtime, and TypeScript's: (name, command, expected text).
CHECKS = [
    (name, check["command"], check["expect"].format(version=PINS["runtimes"][name]["version"]))
    for name in editor_plan.DEFAULT_SET for check in PINS["runtimes"][name]["checks"]
] + [("typescript", "tsc --version", f"Version {EPINS['typescript']['version']}")]


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, **kwargs)


def build(root: Path = ROOT) -> subprocess.CompletedProcess:
    return run([sys.executable, str(BUILD), "--root", str(root)])


def tag(root: Path = ROOT) -> str:
    return run([sys.executable, str(BUILD), "--root", str(root), "--print-tag"]).stdout.strip()


def planted_copy(name: str, dockerfile=None, pins=None) -> Path:
    """A copy of the build's inputs with one defect planted, never touching the tree."""
    target = WORK / name
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    for file in ("pins.json", "editor-pins.json", ".dockerignore"):
        shutil.copy(ROOT / file, target / file)
    shutil.copytree(ROOT / "docker", target / "docker", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "prime", target / "prime", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "lockdown", target / "lockdown", ignore=shutil.ignore_patterns("__pycache__"))
    if dockerfile:
        path = target / editor_plan.DOCKERFILE
        text = path.read_text(encoding="utf-8")
        old, new = dockerfile
        assert text.count(old) == 1, old
        path.write_text(text.replace(old, new), encoding="utf-8")
    if pins:
        path = target / editor_plan.EDITOR_PINS
        data = json.loads(path.read_text(encoding="utf-8"))
        pins(data)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return target


@unittest.skipUnless(os.environ.get("TC_DOCKER") == "1", "set TC_DOCKER=1 to build and run the image")
class TheEditorImage(unittest.TestCase):
    containers: list[str] = []
    volumes: list[str] = []
    planted: list[str] = []

    @classmethod
    def setUpClass(cls):
        built = build()
        if built.returncode != 0:
            raise AssertionError(f"the real editor image did not build:\n{built.stdout[-3000:]}{built.stderr[-3000:]}")
        cls.image = tag()
        cls.editor = cls.start(cls.image)
        cls.wait_healthy(cls.editor)

    @classmethod
    def tearDownClass(cls):
        for name in cls.containers:
            run(["docker", "rm", "-f", name])
        for name in cls.volumes:
            run(["docker", "volume", "rm", "-f", name])
        images = list(cls.planted)
        if os.environ.get("TC_KEEP_IMAGES") != "1":
            images.append(cls.image)
        for image in images:
            run(["docker", "image", "rm", "-f", image])
        shutil.rmtree(WORK, ignore_errors=True)

    # ------------------------------------------------------------ helpers
    @classmethod
    def start(cls, image: str, *extra: str, command: tuple[str, ...] = ()) -> str:
        name = f"tc01-editor-{uuid.uuid4().hex[:8]}"
        cls.containers.append(name)
        started = run(["docker", "run", "-d", "--name", name, "--network", "none", *extra, image, *command])
        assert started.returncode == 0, started.stderr
        return name

    @classmethod
    def volume(cls) -> str:
        name = f"tc01-editor-{uuid.uuid4().hex[:8]}"
        cls.volumes.append(name)
        run(["docker", "volume", "create", name])
        return name

    @staticmethod
    def exec(container: str, *command: str, user: str | None = None, env: dict | None = None):
        options = (["-u", user] if user else []) + [f"-e{k}={v}" for k, v in (env or {}).items()]
        return run(["docker", "exec", *options, container, *command])

    @classmethod
    def healthz(cls, container: str) -> subprocess.CompletedProcess:
        probe = ("import urllib.request as u;"
                 "print(u.urlopen('http://127.0.0.1:8080/healthz', timeout=5).status)")
        return cls.exec(container, "python3", "-c", probe)

    @classmethod
    def wait_healthy(cls, container: str, seconds: int = 60) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if cls.healthz(container).stdout.strip() == "200":
                return True
            time.sleep(1)
        return False

    def planted_build_fails(self, root: Path, *needles: str) -> None:
        self.planted.append(tag(root))
        built = build(root)
        self.assertNotEqual(built.returncode, 0, "the planted build succeeded")
        for needle in needles:
            self.assertIn(needle, built.stdout + built.stderr)

    # ------------------------------------------------------ the toolchains
    def test_every_toolchain_is_found_under_docker_exec_a_login_shell_and_an_interactive_one(self):
        for shell in (["sh", "-c"], ["bash", "-lc"], ["bash", "-ic"]):
            for name, command, expect in CHECKS:
                with self.subTest(shell=" ".join(shell), runtime=name):
                    found = self.exec(self.editor, *shell, command)
                    self.assertEqual(found.returncode, 0, found.stdout + found.stderr)
                    self.assertIn(expect, found.stdout + found.stderr)

    def test_a_login_shell_loses_opt_without_profile_d_while_docker_exec_keeps_it(self):
        """The planted half: profile.d removed from a running container, as root."""
        planted = self.start(self.image)
        removed = self.exec(planted, "rm", "/etc/profile.d/10-editor-toolchain.sh", user="0")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertNotEqual(self.exec(planted, "bash", "-lc", "java -version").returncode, 0)
        self.assertEqual(self.exec(planted, "sh", "-c", "java -version").returncode, 0)
        self.assertEqual(self.exec(self.editor, "bash", "-lc", "java -version").returncode, 0)

    def test_docker_exec_loses_opt_without_env_path(self):
        """The planted half: the base's own PATH, which is what the image would have without ENV."""
        self.assertNotEqual(self.exec(self.editor, "sh", "-c", "java -version", env={"PATH": BASE_PATH}).returncode, 0)
        self.assertEqual(self.exec(self.editor, "sh", "-c", "java -version").returncode, 0)

    def test_a_build_without_profile_d_is_refused_at_its_login_shell_check(self):
        root = planted_copy("no-profile-d", dockerfile=(
            "      > /etc/profile.d/10-editor-toolchain.sh", "      > /tmp/not-profile-d.sh"))
        self.planted_build_fails(root, "failed under bash -lc")

    def test_the_editor_holds_the_runners_trees_and_python_resolves_what_the_runners_does(self):
        runner = self.image_label("org.studyforge.editor.runner")
        digest = runner_plan.inputs_digest(ROOT)
        self.assertEqual(runner, runner_plan.tag_for(editor_plan.DEFAULT_SET, self.arch(), digest))

        def in_runner(script: str) -> str:
            command = ["docker", "run", "--rm", "--network", "none", "--entrypoint", "sh", runner, "-c", script]
            return run(command).stdout

        trees = "cd /opt && LC_ALL=C find . -maxdepth 2 | LC_ALL=C sort"
        editor_trees = self.exec(self.editor, "sh", "-c", trees).stdout.splitlines()
        self.assertEqual([t for t in editor_trees if not t.startswith("./code-server")], in_runner(trees).splitlines())
        script = ("for d in /usr/local/lib/python3*/lib-dynload/*.so; do "
                  "ldd $d | grep -q 'not found' && basename $d; done; true")
        unresolved = in_runner(script)
        self.assertEqual(self.exec(self.editor, "sh", "-c", script).stdout, unresolved)
        self.assertEqual(self.exec(self.editor, "python3", "-c", "import readline").returncode, 0)
        planted = self.start(self.image)
        self.exec(planted, "dpkg", "-r", "--force-depends", "libreadline8t64", user="0")
        self.assertNotEqual(self.exec(planted, "python3", "-c", "import readline").returncode, 0)
        self.assertNotEqual(self.exec(planted, "sh", "-c", script).stdout, unresolved)

    # ------------------------------------------------------- the extensions
    def test_the_installed_extensions_are_exactly_the_pins(self):
        listed = self.exec(self.editor, "code-server", "--extensions-dir", EXTENSIONS_DIR,
                           "--list-extensions", "--show-versions")
        installed = sorted(line.strip() for line in listed.stdout.splitlines() if "@" in line)
        self.assertEqual(installed, sorted([f"{e}@{EPINS['extensions'][e]['version']}" for e in EPINS["extensions"]]
                                           + [LOCKDOWN.expected]))

    def test_an_extension_that_is_not_installed_fails_the_build_naming_it(self):
        root = planted_copy("skip-kotlin", dockerfile=(
            "for vsix in /tmp/fetch/*.vsix /tmp/lockdown/*.vsix; do",
            "for vsix in $(ls /tmp/fetch/*.vsix /tmp/lockdown/*.vsix | grep -v fwcd.kotlin); do"))
        self.planted_build_fails(root, "fwcd.kotlin@0.2.36 is pinned but not installed")

    def test_an_installed_extension_whose_dependency_is_missing_fails_the_build_naming_it(self):
        """Offline, code-server installs it with exit 0; only the image's own check refuses it."""
        root = planted_copy("skip-java", dockerfile=(
            "for vsix in /tmp/fetch/*.vsix /tmp/lockdown/*.vsix; do",
            "for vsix in $(ls /tmp/fetch/*.vsix /tmp/lockdown/*.vsix | grep -v redhat.java); do"))
        path = root / editor_plan.DOCKERFILE
        text = path.read_text(encoding="utf-8").replace(
            "/opt/code-server/extensions ${EXPECTED_EXTENSIONS};",
            "/opt/code-server/extensions $(echo ${EXPECTED_EXTENSIONS} | tr ' ' '\\n' | grep -v redhat.java);")
        path.write_text(text, encoding="utf-8")
        self.planted_build_fails(root, "depends on redhat.java, which is not installed")

    # ------------------------------------------------- the workbench lockdown
    def test_the_lockdown_is_loaded_in_the_running_container_and_a_copied_folder_is_not(self):
        """TC-04's acceptance, read from the INSTALLED list rather than from a file being there.

        And the other way, which is the whole reason it is packaged: a folder
        copied into the extensions directory is present, correct, and never
        loaded, because the workbench reads `extensions.json` and never scans.
        """
        listed = self.exec(self.editor, "code-server", "--extensions-dir", EXTENSIONS_DIR,
                           "--list-extensions", "--show-versions")
        self.assertIn(LOCKDOWN.expected, [line.strip() for line in listed.stdout.splitlines()])
        registered = json.loads(self.exec(self.editor, "cat", f"{EXTENSIONS_DIR}/extensions.json").stdout)
        self.assertIn(LOCKDOWN.id, [entry["identifier"]["id"] for entry in registered])
        held = self.exec(self.editor, "sh", "-c", f"ls -d {EXTENSIONS_DIR}/{LOCKDOWN.id}-*").stdout.strip()
        self.assertTrue(held, "the installed extension has a folder of its own")
        copied = self.start(self.image)
        self.exec(copied, "sh", "-c",
                  f"cp -r {held} {EXTENSIONS_DIR}/example.copied-1.0.0 && "
                  f'sed -i \'s/"practice-focus"/"copied"/; s/"studyforge"/"example"/\' '
                  f"{EXTENSIONS_DIR}/example.copied-1.0.0/package.json", user="0")
        after = self.exec(copied, "code-server", "--extensions-dir", EXTENSIONS_DIR, "--list-extensions")
        self.assertIn(LOCKDOWN.id, after.stdout)
        self.assertNotIn("example.copied", after.stdout, "a copied folder is never loaded")

    def test_a_lockdown_that_is_packed_but_not_installed_fails_the_build_naming_it(self):
        root = planted_copy("skip-lockdown", dockerfile=(
            "for vsix in /tmp/fetch/*.vsix /tmp/lockdown/*.vsix; do", "for vsix in /tmp/fetch/*.vsix; do"))
        self.planted_build_fails(root, f"{LOCKDOWN.expected} is pinned but not installed")

    def test_a_file_that_is_not_the_pinned_one_stops_the_build_before_anything_is_installed(self):
        def wrong(pins):
            pins["extensions"]["fwcd.kotlin"]["files"]["universal"]["sha256"] = "0" * 64
        root = planted_copy("wrong-sha", pins=wrong)
        self.planted_build_fails(root, "fwcd.kotlin-0.2.36.vsix: sha256", "is not the value editor-pins.json records")

    # -------------------------------------------------- starting and seeding
    def test_the_editor_starts_and_answers_its_health_check_from_inside(self):
        self.assertEqual(self.healthz(self.editor).stdout.strip(), "200")
        idle = self.start(self.image, "--entrypoint", "sleep", command=["infinity"])
        self.assertNotEqual(self.healthz(idle).stdout.strip(), "200", "nothing serves when code-server is not started")

    def test_the_seed_is_written_once_and_never_overwrites_the_readers_settings(self):
        data = self.volume()
        first = self.start(self.image, "-v", f"{data}:/home/coder/.local")
        self.assertTrue(self.wait_healthy(first))
        target = "/home/coder/.local/share/code-server/User/settings.json"
        seeded = self.exec(first, "cat", target).stdout
        self.assertIn('"name": "JavaSE-' + PINS["runtimes"]["java"]["version"].split(".")[0] + '"', seeded)
        self.assertNotIn("@JAVA_RUNTIME@", seeded)
        self.exec(first, "sh", "-c", f"echo '{{\"mine\": true}}' > {target}")
        run(["docker", "rm", "-f", first])
        second = self.start(self.image, "-v", f"{data}:/home/coder/.local")
        self.assertTrue(self.wait_healthy(second))
        self.assertEqual(self.exec(second, "cat", target).stdout.strip(), '{"mine": true}')
        logs = run(["docker", "logs", second])
        self.assertIn("leaving them alone", logs.stdout + logs.stderr)

    def test_volume_mount_points_are_owned_by_the_runtime_uid_and_a_missing_one_would_not_be(self):
        for path in ("/home/coder/.config", "/home/coder/.local", "/home/coder/.gradle"):
            with self.subTest(path=path):
                volume = self.volume()
                owner = run(["docker", "run", "--rm", "--network", "none", "-v", f"{volume}:{path}",
                             "--entrypoint", "stat", self.image, "-c", "%u", path])
                self.assertEqual(owner.stdout.strip(), "1000")
        volume = self.volume()
        owner = run(["docker", "run", "--rm", "--network", "none", "-v", f"{volume}:/home/coder/.absent",
                     "--entrypoint", "stat", self.image, "-c", "%u", "/home/coder/.absent"])
        self.assertEqual(owner.stdout.strip(), "0", "a mount point absent from the image comes up root-owned")

    # ------------------------------------------------------------- the shape
    def test_entrypoint_and_cmd_are_redeclared_because_the_base_bakes_arguments(self):
        config = self.inspect(self.image)
        self.assertEqual(config["Entrypoint"], ["/opt/code-server/entrypoint.sh"])
        self.assertIn(f"--extensions-dir={EXTENSIONS_DIR}", config["Cmd"])
        base = self.inspect(f"{EPINS['base']['image']}@{EPINS['base']['digest']}")
        self.assertGreater(len(base["Entrypoint"]), 1, "the base's ENTRYPOINT carries arguments")

    def test_the_image_carries_no_docker_and_no_socket_and_declares_its_set(self):
        self.assertNotEqual(self.exec(self.editor, "sh", "-c", "command -v docker").returncode, 0)
        self.assertNotEqual(self.exec(self.editor, "test", "-e", "/var/run/docker.sock").returncode, 0)
        self.assertEqual(self.image_label("org.studyforge.editor.runtimes"), " ".join(editor_plan.DEFAULT_SET))

    # --------------------------------------------------------------- support
    @staticmethod
    def inspect(image: str) -> dict:
        return json.loads(run(["docker", "image", "inspect", image]).stdout)[0]["Config"]

    def image_label(self, label: str) -> str:
        return self.inspect(self.image)["Labels"][label]

    def arch(self) -> str:
        return re.search(r"-(amd64|arm64)-[0-9a-f]{12}$", self.image).group(1)


if __name__ == "__main__":
    unittest.main()
