"""The compose contract, brought up for real — every assertion BOTH ways.

⛔ Skipped unless `TC_DOCKER=1`: it builds an image, starts containers and
publishes a loopback port. Run it as ONE container job (the whole module under
whatever lock the host uses):

    TC_DOCKER=1 python3 -m unittest tests.test_consuming_image -v

⭐ **What it demonstrates.** The acceptance is that a consumer following
`docs/consuming.md` reaches a working container with only its own compose file.
So this module copies the CHECKED-IN reference fragment verbatim into an empty
directory, supplies only what the fragment itself asks for by name, and brings
it up. Nothing in the fragment is edited.

⭐ **The versioning half (`TC-06`).** One clause builds a SECOND image from a
second declared set and brings it up beside the first, in its own compose
project and on its own port: two consumers holding two tags, both healthy at
once, each container wearing its own set's label. Another runs the image with a
read-only root filesystem and measures that it never starts, which is the
failure ruling 5 is made of.

Every image, container and volume it creates is removed afterwards — both editor
images too, unless `TC_KEEP_IMAGES=1`. The planted half of the bind-source ruling
leaves a root-owned directory behind on purpose; it is removed from inside a
container, since the host user cannot.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "consuming"))
sys.path.insert(0, str(ROOT / "docker" / "editor"))

import consuming  # noqa: E402
import editor_plan  # noqa: E402

BUILD = ROOT / "docker" / "editor" / "build.py"
WORK = ROOT / ".work" / "tests-consuming"
CONTRACT = consuming.load(ROOT)
EDITOR = CONTRACT["editor"]
REFERENCE = ROOT / consuming.REFERENCE
#: The cheapest declared set that still carries a build tool; the contract is
#: about the run shape, which no runtime changes.
RUNTIMES = "java,maven"
#: A SECOND consumer's declared set, for the two-tags-at-once acceptance. It is
#: a subset of the first, so its runner stages and its extensions are already
#: built and only the layers the set changes are paid for.
OTHER_RUNTIMES = "java"
PASSWORD = "a-password-for-this-test"
SOURCES = Path(EDITOR["mounts"][0]["host_path"])
PORT = EDITOR["ports"][0]["host"]


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, **kwargs)


def taken(port: int) -> bool:
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) == 0


def free_port() -> int:
    """A loopback port nothing holds, for a SECOND consumer beside the first."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@unittest.skipUnless(os.environ.get("TC_DOCKER") == "1", "set TC_DOCKER=1 to build and run the image")
@unittest.skipIf(taken(PORT), f"the reference fragment publishes {PORT}, which is in use")
class TheComposeContract(unittest.TestCase):
    """The reference fragment, copied verbatim and brought up as a consumer would."""

    projects: list[tuple[str, Path]] = []

    @classmethod
    def setUpClass(cls):
        built = run([sys.executable, str(BUILD), "--runtimes", RUNTIMES])
        if built.returncode != 0:
            raise AssertionError(f"the editor image did not build:\n{built.stdout[-3000:]}{built.stderr[-3000:]}")
        cls.image = built.stdout.strip().splitlines()[-1]
        cls.project, cls.directory = cls.consumer("up", sources=True)
        brought = cls.compose(cls.project, cls.directory, "up", "-d", "--wait")
        assert brought.returncode == 0, brought.stdout + brought.stderr
        cls.container = cls.compose(cls.project, cls.directory, "ps", "-q", "editor").stdout.strip()

    @classmethod
    def tearDownClass(cls):
        for project, directory in cls.projects:
            cls.compose(project, directory, "down", "-v", "--remove-orphans")
        # A bind source docker created is root-owned: only a root container can remove it.
        if WORK.is_dir():
            run(["docker", "run", "--rm", "--network", "none", "--user", "0",
                 "--entrypoint", "sh", "-v", f"{WORK}:/work", cls.image, "-c", "rm -rf /work/*"])
        if os.environ.get("TC_KEEP_IMAGES") != "1":
            run(["docker", "image", "rm", "-f", cls.image])
        shutil.rmtree(WORK, ignore_errors=True)

    # ------------------------------------------------------------- helpers
    @classmethod
    def consumer(cls, label: str, *, sources: bool, port: int | None = None) -> tuple[str, Path]:
        """An empty directory holding the checked-in fragment, copied and not edited.

        ⚠️ `port` is for a SECOND consumer running beside the first, which cannot
        publish the same one. `editor.ports[0].host` is `per_project: true`, so
        that project's file is rendered from the contract with its own port —
        the only project whose file is not the checked-in bytes.
        """
        project = f"tc05-{label}-{uuid.uuid4().hex[:8]}"
        directory = WORK / project
        directory.mkdir(parents=True)
        if port is None:
            shutil.copy(REFERENCE, directory / "compose.yaml")
        else:
            adapted = json.loads(json.dumps(CONTRACT))
            adapted["editor"]["ports"][0]["host"] = port
            (directory / "compose.yaml").write_text(consuming.render(adapted), encoding="utf-8")
        if sources:
            (directory / SOURCES).mkdir()
            (directory / SOURCES / "a-source.txt").write_text("written on the host\n", encoding="utf-8")
        cls.projects.append((project, directory))
        return project, directory

    @classmethod
    def compose(cls, project: str, directory: Path, *arguments: str,
                image: str | None = None) -> subprocess.CompletedProcess:
        """`docker compose` with only what the fragment asks for by name, in its own project."""
        environment = dict(os.environ, EDITOR_IMAGE=image or cls.image, CODE_SERVER_PASSWORD=PASSWORD,
                           HOST_UID=str(os.getuid()), HOST_GID=str(os.getgid()))
        return run(["docker", "compose", "--project-name", project, "-f", str(directory / "compose.yaml"),
                    *arguments], cwd=directory, env=environment)

    @staticmethod
    def inspect(container: str) -> dict:
        return json.loads(run(["docker", "inspect", container]).stdout)[0]

    @staticmethod
    def exec(container: str, *command: str, user: str | None = None) -> subprocess.CompletedProcess:
        return run(["docker", "exec", *(["-u", user] if user else []), container, *command])

    @staticmethod
    def fetch(path: str) -> tuple[int, str]:
        request = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}",
                                         headers={"User-Agent": "Example/0.1 (+https://example.invalid)"})
        try:
            with urllib.request.urlopen(request, timeout=10) as answer:
                return answer.status, answer.url
        except urllib.error.HTTPError as refused:
            return refused.status, refused.url

    # ------------------------------------------- it is a working container
    def test_the_editor_answers_the_declared_health_path_on_loopback(self):
        status, _ = self.fetch(EDITOR["healthcheck"]["path"])
        self.assertEqual(status, EDITOR["healthcheck"]["expect_status"])
        self.assertEqual(self.inspect(self.container)["State"]["Health"]["Status"], "healthy")

    def test_the_reader_sees_the_sources_that_were_on_the_host(self):
        found = self.exec(self.container, "cat", f"{EDITOR['mounts'][0]['container_path']}/a-source.txt")
        self.assertEqual(found.stdout, "written on the host\n")

    def test_it_never_starts_unauthenticated(self):
        status, where = self.fetch("/")
        self.assertIn("/login", where, f"the root answered {status} without asking for the password")

    # -------------------------------------- ruling 1: loopback only, never 0.0.0.0
    def test_the_published_port_is_bound_to_loopback_and_to_nothing_else(self):
        published = self.inspect(self.container)["HostConfig"]["PortBindings"]
        declared = f"{EDITOR['ports'][0]['container']}/{EDITOR['ports'][0]['protocol']}"
        self.assertEqual(list(published), [declared])
        for binding in published[declared]:
            self.assertIn(binding["HostIp"], consuming.LOOPBACK)
            self.assertEqual(binding["HostPort"], str(PORT))

    def test_a_fragment_rendered_without_that_ruling_is_refused_before_compose_sees_it(self):
        broken = json.loads(json.dumps(CONTRACT))
        broken["editor"]["ports"][0]["host_bind"] = "0.0.0.0"
        with self.assertRaises(consuming.Refused):
            consuming.render(broken)

    # ------------------------------ ruling 2: only the sources, not the repository
    def test_the_only_host_directory_it_can_reach_is_the_sources(self):
        bound = [mount for mount in self.inspect(self.container)["Mounts"] if mount["Type"] == "bind"]
        self.assertEqual([mount["Destination"] for mount in bound],
                         [EDITOR["mounts"][0]["container_path"]])
        self.assertTrue(bound[0]["Source"].endswith(f"/{SOURCES}"), bound[0]["Source"])

    def test_the_workspace_root_is_a_tmpfs_the_running_user_can_write(self):
        root = EDITOR["workspace"]["container_path"]
        self.assertIn(root, self.inspect(self.container)["HostConfig"]["Tmpfs"])
        wrote = self.exec(self.container, "sh", "-c", f"touch {root}/a-build-artifact")
        self.assertEqual(wrote.returncode, 0, wrote.stderr)

    # ------------------------------------ ruling 3: the repository owner's uid:gid
    def test_a_file_the_container_creates_in_the_sources_belongs_to_the_host_user(self):
        made = f"{EDITOR['mounts'][0]['container_path']}/made-in-container.txt"
        wrote = self.exec(self.container, "sh", "-c", f"echo written inside > {made}")
        self.assertEqual(wrote.returncode, 0, wrote.stderr)
        on_host = self.directory / SOURCES / "made-in-container.txt"
        self.assertEqual(on_host.stat().st_uid, os.getuid())
        self.assertNotEqual(on_host.stat().st_uid, 0)

    def test_a_uid_that_is_not_the_images_own_starts_and_a_build_without_fixuid_does_not(self):
        """The entrypoint runs fixuid before it seeds; without that, HOME is `/` and it exits."""
        stranger = "4321:4321"
        started = self.editor_as(stranger)
        self.assertTrue(self.wait_healthy(started), run(["docker", "logs", started]).stderr)
        self.assertEqual(self.exec(started, "sh", "-c", "echo $HOME").stdout.strip(), "/home/coder")

        planted = WORK / "entrypoint-without-fixuid.sh"
        text = (ROOT / "docker" / "editor" / "entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn('eval "$(fixuid -q)"\n', text)
        planted.write_text(text.replace('eval "$(fixuid -q)"\n', ""), encoding="utf-8")
        planted.chmod(0o755)
        broken = self.editor_as(stranger, "-v", f"{planted}:/opt/code-server/entrypoint.sh:ro")
        self.assertFalse(self.wait_healthy(broken, seconds=20), "the planted entrypoint started anyway")
        logged = run(["docker", "logs", broken])
        self.assertIn("Permission denied", logged.stdout + logged.stderr)

    def editor_as(self, user: str, *extra: str) -> str:
        name = f"tc05-user-{uuid.uuid4().hex[:8]}"
        self.addCleanup(run, ["docker", "rm", "-f", name])
        started = run(["docker", "run", "-d", "--name", name, "--network", "none", "--user", user,
                       *extra, self.image, *EDITOR["command"]])
        self.assertEqual(started.returncode, 0, started.stderr)
        return name

    def wait_healthy(self, container: str, seconds: int = 60) -> bool:
        deadline = time.monotonic() + seconds
        probe = list(EDITOR["healthcheck"]["command"][1:])
        while time.monotonic() < deadline:
            if self.exec(container, *probe).returncode == 0:
                return True
            if self.inspect(container)["State"]["Status"] == "exited":
                return False
            time.sleep(1)
        return False

    # ---------------------- ruling 4: a bind source must exist before the start
    def test_a_missing_bind_source_is_created_root_owned_and_the_reader_cannot_write_it(self):
        project, directory = self.consumer("no-sources", sources=False, port=free_port())
        brought = self.compose(project, directory, "up", "-d")
        self.assertEqual(brought.returncode, 0, brought.stderr)
        made = directory / SOURCES
        self.assertTrue(made.is_dir(), "docker did not create the missing bind source")
        self.assertEqual(made.stat().st_uid, 0, "the measured failure did not reproduce")
        container = self.compose(project, directory, "ps", "-q", "editor").stdout.strip()
        refused = self.exec(container, "sh", "-c",
                            f"touch {EDITOR['mounts'][0]['container_path']}/never-written")
        self.assertNotEqual(refused.returncode, 0, "the reader could write a root-owned bind source")

    def test_every_bind_the_contract_declares_says_it_must_exist_first(self):
        binds = [mount for mount in EDITOR["mounts"] if mount["kind"] == "bind"]
        self.assertTrue(binds)
        for mount in binds:
            self.assertIs(mount["must_exist_before_start"], True, mount["container_path"])

    # ------------------- ruling 5: the root filesystem stays writable (W390/3)
    def test_a_read_only_root_filesystem_never_starts_and_the_declared_one_does(self):
        """The entrypoint repairs the passwd record at every start; /etc is written."""
        self.assertIs(EDITOR["filesystem"]["read_only_root"], False)
        refused = self.editor_as(f"{os.getuid()}:{os.getgid()}", "--read-only")
        self.assertFalse(self.wait_healthy(refused, seconds=20), "a read-only root started anyway")
        logged = run(["docker", "logs", refused])
        self.assertIn("Read-only file system", logged.stdout + logged.stderr)
        self.assertEqual(self.inspect(self.container)["HostConfig"]["ReadonlyRootfs"], False)

    def test_the_fragment_covers_none_of_the_paths_that_must_stay_writable(self):
        protected = EDITOR["filesystem"]["never_read_only"]
        self.assertTrue(protected)
        for mount in self.inspect(self.container)["Mounts"]:
            for path in protected:
                with self.subTest(mount=mount["Destination"], path=path):
                    self.assertFalse(mount["Destination"] == path
                                     or mount["Destination"].startswith(f"{path}/"), mount)

    # ----------------- TC-06: two consumers pin two tags and run them at once
    def test_two_consumers_pin_two_tags_and_run_them_side_by_side(self):
        """Acceptance: two consumers can pin different tags simultaneously."""
        built = run([sys.executable, str(BUILD), "--runtimes", OTHER_RUNTIMES])
        self.assertEqual(built.returncode, 0, built.stdout[-3000:] + built.stderr[-3000:])
        other = built.stdout.strip().splitlines()[-1]
        self.assertNotEqual(other, self.image, "two declared sets computed one tag")
        project, directory = self.consumer("other-tag", sources=True, port=free_port())
        if os.environ.get("TC_KEEP_IMAGES") != "1":
            self.addCleanup(run, ["docker", "image", "rm", "-f", other])
        self.addCleanup(self.compose, project, directory, "down", "-v", "--remove-orphans")

        brought = self.compose(project, directory, "up", "-d", "--wait", image=other)
        self.assertEqual(brought.returncode, 0, brought.stdout[-2000:] + brought.stderr[-2000:])
        second = self.compose(project, directory, "ps", "-q", "editor").stdout.strip()
        label = EDITOR["image"]["labels"]["runtimes"]
        for container, declared in ((self.container, RUNTIMES), (second, OTHER_RUNTIMES)):
            with self.subTest(container=declared):
                found = self.inspect(container)
                self.assertEqual(found["State"]["Health"]["Status"], "healthy")
                self.assertEqual(found["Config"]["Labels"][label].split(), declared.split(","))
        self.assertNotEqual(self.inspect(self.container)["Image"], self.inspect(second)["Image"])

    # ---------------------------------------------- §8.3: never a Docker socket
    def test_no_docker_socket_and_no_docker_cli_is_inside_the_container(self):
        self.assertEqual([mount for mount in self.inspect(self.container)["Mounts"]
                          if "docker.sock" in mount.get("Source", "")], [])
        self.assertNotEqual(self.exec(self.container, "test", "-e", "/var/run/docker.sock").returncode, 0)
        self.assertNotEqual(self.exec(self.container, "sh", "-lc", "command -v docker").returncode, 0)

    # -------------------------------------- what the image brings, not the file
    def test_the_lockdown_the_contract_names_is_installed_in_this_container(self):
        listed = self.exec(self.container, "code-server",
                           f"--extensions-dir={EDITOR['extensions']['installed_at']}", "--list-extensions")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        for identifier in EDITOR["extensions"]["always_installed"]:
            self.assertIn(identifier, listed.stdout)
        self.assertEqual(EDITOR["extensions"]["always_installed"],
                         [editor_plan.lockdown_identity(ROOT).id])

    def test_the_seeded_settings_were_written_once_and_belong_to_the_running_user(self):
        seeded = "/home/coder/.local/share/code-server/User/settings.json"
        found = self.exec(self.container, "stat", "-c", "%u", seeded)
        self.assertEqual(found.stdout.strip(), str(os.getuid()))


if __name__ == "__main__":
    unittest.main()
