"""The consuming contract, its document and its reference fragment — no Docker needed.

Run from the component root: `python3 -m unittest discover -s tests -v`.
Every rule is asserted BOTH ways: the real contract passes, and a planted
violation is caught.

⭐ The third class is the anti-drift one. `consuming.json` describes an image
this repository builds, so every value it states about that image is read back
out of the build's own plan, the Dockerfile and the lockdown manifest. A
contract that goes stale fails here rather than in a consumer's browser.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "consuming"))
sys.path.insert(0, str(ROOT / "docker" / "editor"))

import consuming  # noqa: E402
import editor_plan  # noqa: E402

runner_plan = editor_plan.runner_plan
CONTRACT = consuming.load(ROOT)
EDITOR = CONTRACT["editor"]
PINS = runner_plan.load(ROOT)
DOCKERFILE = (ROOT / editor_plan.DOCKERFILE).read_text(encoding="utf-8")
ENTRYPOINT = (ROOT / "docker" / "editor" / "entrypoint.sh").read_text(encoding="utf-8")
DOCUMENT = (ROOT / "docs" / "consuming.md").read_text(encoding="utf-8")
REFERENCE = (ROOT / consuming.REFERENCE).read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
LOCKDOWN = editor_plan.lockdown_identity(ROOT)
#: A backticked key path this document claims the contract carries.
KEY_PATH = re.compile(r"`(editor(?:\.[a-z_]+|\[\d+\])+)`")


def planted(**changes) -> dict:
    """A copy of the real contract with one value replaced, never touching the tree."""
    contract = copy.deepcopy(CONTRACT)
    for path, value in changes.items():
        cursor = contract["editor"]
        *steps, last = path.split(".")
        for step in steps:
            cursor = cursor[int(step)] if step.isdigit() else cursor[step]
        cursor[int(last) if last.isdigit() else last] = value
    return contract


def resolve(contract: dict, path: str):
    cursor = contract
    for step in re.findall(r"[a-z_]+|\d+", path):
        cursor = cursor[int(step)] if step.isdigit() else cursor[step]
    return cursor


class TheContract(unittest.TestCase):
    def test_the_real_contract_breaks_no_ruling(self):
        self.assertEqual(consuming.findings(CONTRACT), [])

    def test_it_carries_the_two_versions_and_names_its_own_holes(self):
        self.assertEqual(CONTRACT["consuming_api"], 1)
        self.assertIsInstance(CONTRACT["provides"], int)
        self.assertEqual(CONTRACT["component"], "code-server-toolchain")
        self.assertTrue(all(isinstance(hole, str) and hole for hole in CONTRACT["not_yet_declared"]))

    def test_each_planted_defect_is_found(self):
        plants = {
            "docker_socket": (planted(docker_socket=True), "Docker socket is never mounted"),
            "a socket mount": (planted(**{"mounts.0.host_path": "/var/run/docker.sock"}),
                               "a mount names the Docker socket"),
            "published off loopback": (planted(**{"ports.0.host_bind": "0.0.0.0"}), "0.0.0.0"),
            "published on every interface": (planted(**{"ports.0.publish_on_all_interfaces": True}),
                                             "binds loopback only"),
            "a port nothing publishes": (planted(**{"ports.0.container": 9090}),
                                         "which no ports entry publishes"),
            "a bind address with no port": (planted(**{"command.1": "--bind-addr"}),
                                            "which no ports entry publishes"),
            "runs as root": (planted(**{"runs_as.uid": 0}), "runs as the uid:gid that owns the sources"),
            "no compose value for the user": (planted(**{"runs_as.compose_value": ""}),
                                              "nothing to put under `user:`"),
            "the workspace is not a tmpfs": (planted(**{"workspace.kind": "volume"}),
                                             "the workspace root is not a tmpfs"),
            "a bind outside the workspace": (planted(**{"mounts.0.container_path": "/home/coder"}),
                                             "only the sources are mounted"),
            "a bind that may be created by docker": (planted(**{"mounts.0.must_exist_before_start": False}),
                                                     "docker creates a missing one root-owned"),
            "no health check": (planted(healthcheck={}), "ordering is enforced by a health check"),
            "required and defaulted": (planted(**{"environment.0.default": "letmein"}),
                                       "is required and defaulted"),
        }
        for name, (contract, needle) in plants.items():
            with self.subTest(plant=name):
                found = consuming.findings(contract)
                self.assertTrue(found, "the planted contract reported nothing")
                self.assertTrue(any(needle in finding for finding in found), found)

    def test_a_contract_with_a_finding_is_refused_rather_than_rendered(self):
        with self.assertRaises(consuming.Refused) as refusal:
            consuming.render(planted(docker_socket=True))
        self.assertIn("Docker socket", str(refusal.exception))

    def test_the_cli_checks_renders_and_refuses(self):
        def cli(*argv, root=ROOT):
            return subprocess.run([sys.executable, str(ROOT / "consuming" / "consuming.py"),
                                   "--root", str(root), *argv],
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True)

        self.assertEqual(cli("--check").returncode, 0)
        self.assertEqual(cli("--render").stdout, REFERENCE)


class TheRenderedFragment(unittest.TestCase):
    """It is generated from the contract and nothing else, and it is a template."""

    def test_the_checked_in_fragment_is_what_the_contract_renders_today(self):
        self.assertEqual(REFERENCE, consuming.render(CONTRACT),
                         "regenerate it: python3 consuming/consuming.py --write " + consuming.REFERENCE)

    def test_it_says_it_is_a_template_and_not_an_include(self):
        self.assertIn("TEMPLATE TO COPY AND ADAPT", REFERENCE)
        self.assertIn("never an `include:`", REFERENCE)
        self.assertNotIn("\ninclude:", REFERENCE)

    def test_it_publishes_only_loopback_and_mounts_no_socket(self):
        published = re.findall(r'^\s+- "([^"]*:\d+:\d+)"$', REFERENCE, flags=re.MULTILINE)
        self.assertTrue(published)
        for entry in published:
            self.assertIn(entry.rsplit(":", 2)[0], consuming.LOOPBACK)
        self.assertNotIn("docker.sock", REFERENCE)

    def test_it_renders_every_mount_the_contract_declares(self):
        for mount in EDITOR["mounts"]:
            source = mount["host_path"] if mount["kind"] == "bind" else mount["volume"]
            with self.subTest(mount=mount["container_path"]):
                self.assertIn(f'- "{source}:{mount["container_path"]}"', REFERENCE)

    def test_a_renamed_volume_moves_the_mount_and_the_volumes_block_together(self):
        renamed = consuming.render(planted(**{"mounts.1.volume": "somewhere-else"}))
        self.assertIn('- "somewhere-else:/home/coder/.config"', renamed)
        self.assertIn("\n  somewhere-else:", renamed)
        self.assertNotIn("editor-config", renamed)

    @unittest.skipUnless(shutil.which("docker"), "the Docker CLI parses the compose file")
    def test_compose_itself_accepts_it(self):
        parsed = subprocess.run(["docker", "compose", "-f", str(ROOT / consuming.REFERENCE), "config"],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                env={"PATH": "/usr/bin:/bin:/usr/local/bin", "EDITOR_IMAGE": "an-image",
                                     "CODE_SERVER_PASSWORD": "a-password"})
        self.assertEqual(parsed.returncode, 0, parsed.stderr)
        self.assertIn("host_ip: 127.0.0.1", parsed.stdout)


class TheContractAgreesWithTheImage(unittest.TestCase):
    """Every value the contract states about the image is read back out of the build."""

    def test_the_repository_and_the_build_command_are_the_editors_own(self):
        self.assertEqual(EDITOR["image"]["repository"], editor_plan.REPOSITORY)
        self.assertIsNone(EDITOR["image"]["registry"])
        for command in (EDITOR["image"]["built_by"], EDITOR["image"]["tag_from"]):
            self.assertTrue((ROOT / command[1]).is_file(), command)
            self.assertIn("--runtimes", command)
        self.assertIn("--print-tag", EDITOR["image"]["tag_from"])
        for label in EDITOR["image"]["labels"].values():
            self.assertIn(label, DOCKERFILE)

    def test_the_declared_runtimes_are_the_pinned_ones_the_editor_can_carry(self):
        carried = sorted(set(PINS["runtimes"]) - set(editor_plan.NOT_CARRIED))
        self.assertEqual(EDITOR["runtimes"]["selectable"], carried)
        self.assertEqual(EDITOR["runtimes"]["default_set"], list(editor_plan.DEFAULT_SET))
        self.assertEqual(EDITOR["runtimes"]["not_carried"], editor_plan.NOT_CARRIED)

    def test_the_uid_and_the_volume_mount_points_are_the_dockerfiles_own(self):
        runs_as = EDITOR["runs_as"]
        self.assertIn(f"\nUSER {runs_as['uid']}\n", DOCKERFILE)
        created = re.search(r"RUN install -d -o (\d+) -g (\d+) (.+)", DOCKERFILE)
        self.assertEqual((int(created[1]), int(created[2])), (runs_as["uid"], runs_as["gid"]))
        declared = [mount["container_path"] for mount in EDITOR["mounts"] if mount["kind"] == "volume"]
        self.assertEqual(sorted(declared), sorted(created[3].split()))

    def test_the_port_and_the_extensions_directory_are_the_images_cmd(self):
        cmd = json.loads(re.search(r"^CMD (\[.*\])$", DOCKERFILE, flags=re.MULTILINE)[1])
        self.assertIn(f"0.0.0.0:{EDITOR['ports'][0]['container']}", cmd)
        self.assertIn(f"--extensions-dir={EDITOR['extensions']['installed_at']}", cmd)

    def test_the_command_replaces_that_cmd_rather_than_extending_it(self):
        command = EDITOR["command"]
        self.assertEqual(command[-1], EDITOR["workspace"]["container_path"])
        self.assertIn(f"--bind-addr=0.0.0.0:{EDITOR['ports'][0]['container']}", command)
        self.assertIn(f"--extensions-dir={EDITOR['extensions']['installed_at']}", command)
        self.assertTrue(any(argument.startswith("--auth=") for argument in command),
                        "the IDE must never start unauthenticated")

    def test_the_extension_ids_are_the_lockdown_manifests_own(self):
        self.assertEqual(EDITOR["extensions"]["always_installed"], [LOCKDOWN.id])
        contributed = sorted(json.loads((ROOT / "lockdown" / "package.json").read_text(encoding="utf-8"))
                             ["contributes"]["configuration"]["properties"])
        self.assertEqual(EDITOR["extensions"]["settings_a_study_server_writes"], contributed)

    def test_the_entrypoint_repairs_the_uid_before_it_seeds_anything(self):
        """Ruling 3's mechanism: without this ordering a uid but 1000 has HOME=/ here."""
        self.assertIn('eval "$(fixuid -q)"', ENTRYPOINT)
        self.assertLess(ENTRYPOINT.index('eval "$(fixuid -q)"'), ENTRYPOINT.index('seed_tree "$SEED_GRADLE"'))
        self.assertIn("fixuid", EDITOR["runs_as"]["how"])

    def test_the_health_checks_interpreter_is_the_one_every_set_carries(self):
        interpreter = EDITOR["healthcheck"]["command"][1]
        self.assertTrue(interpreter.startswith("/usr/lib/code-server/"), interpreter)
        self.assertIn(f"127.0.0.1:{EDITOR['healthcheck']['port']}{EDITOR['healthcheck']['path']}",
                      EDITOR["healthcheck"]["command"][-1])


class TheDocument(unittest.TestCase):
    """It quotes the contract instead of restating it, and every key it names exists."""

    def test_every_key_path_it_names_resolves_in_the_contract(self):
        paths = sorted(set(KEY_PATH.findall(DOCUMENT)))
        self.assertGreater(len(paths), 20, paths)
        for path in paths:
            with self.subTest(path=path):
                resolve(CONTRACT, path)

    def test_a_key_path_the_contract_does_not_carry_would_be_caught(self):
        with self.assertRaises(KeyError):
            resolve(CONTRACT, "editor.ports[0].host_interface")

    def test_it_names_every_section_the_contract_carries(self):
        for section in EDITOR:
            with self.subTest(section=section):
                self.assertIn(f"editor.{section}", DOCUMENT)

    def test_it_states_each_of_the_four_rulings_with_its_failure(self):
        rulings = ("Loopback-only port binding", "Mount only the sources",
                   "Run as the repository owner's uid:gid",
                   "A bind source must exist on the host before the container starts")
        for ruling in rulings:
            with self.subTest(ruling=ruling):
                section = DOCUMENT.split(ruling, 1)
                self.assertEqual(len(section), 2, "the ruling is not stated")
                self.assertIn("The failure", section[1].split("\n### ", 1)[0])

    def test_it_marks_the_fragment_a_template_and_forbids_reading_the_dockerfile(self):
        self.assertIn("TEMPLATE, not an include", DOCUMENT)
        self.assertIn("never reads the `Dockerfile`", DOCUMENT)

    def test_the_readme_sends_a_consumer_here_and_no_longer_defers_it(self):
        self.assertIn("docs/consuming.md", README)
        self.assertNotIn("which is a later task's", README)
        self.assertEqual(runner_plan.run_line_findings(README), [])


if __name__ == "__main__":
    unittest.main()
