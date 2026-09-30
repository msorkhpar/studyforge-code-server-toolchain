"""The runner block of the consuming contract, and the two lines it renders — no Docker needed.

Run from the component root: `python3 -m unittest discover -s tests -v`.
Every rule is asserted BOTH ways: the real block passes, and a planted
violation is caught.

⭐ `tests/test_consuming.py` is the editor's half of this file and the shape is
deliberately the same — the contract, the rendering, the agreement with the
image, the document. The anti-drift class is the point of the row: the runner's
run shape used to live only in the README's prose, so the framework had to
re-derive it by parsing that sentence. It is now data, and the
README's line is asserted to be what the data renders.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "consuming"))
sys.path.insert(0, str(ROOT / "docker" / "minimal"))

import consuming  # noqa: E402
import plan as runner_plan  # noqa: E402
import runner  # noqa: E402

CONTRACT = consuming.load(ROOT)
RUNNER = CONTRACT[runner.BLOCK]
PINS = runner_plan.load(ROOT)
DOCKERFILE = (ROOT / runner_plan.DOCKERFILE).read_text(encoding="utf-8")
DOCUMENT = (ROOT / "docs" / "consuming.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
#: A backticked key path this document claims the RUNNER block carries.
KEY_PATH = re.compile(r"`(runner(?:\.[a-z_]+|\[\d+\])+)`")


def planted(**changes) -> dict:
    """A copy of the real runner block with one value replaced, never touching the tree."""
    block = copy.deepcopy(RUNNER)
    for path, value in changes.items():
        cursor = block
        *steps, last = path.split(".")
        for step in steps:
            cursor = cursor[int(step)] if step.isdigit() else cursor[step]
        cursor[int(last) if last.isdigit() else last] = value
    return block


def resolve(contract: dict, path: str):
    cursor = contract
    for step in re.findall(r"[a-z_]+|\d+", path):
        cursor = cursor[int(step)] if step.isdigit() else cursor[step]
    return cursor


def documented(keyword: str, text: str = README, continuation: str = "\\") -> str:
    """The first line of `text` starting with `keyword`, continuations joined."""
    joined, current = [], ""
    for line in text.splitlines():
        if line.rstrip().endswith(continuation):
            current += line.rstrip()[:-1] + " "
            continue
        joined.append(current + line)
        current = ""
    line = next(one for one in joined if one.lstrip().startswith(keyword))
    return " ".join(line.split())


def fenced(text: str, language: str) -> str:
    """Every fenced block of `language` in `text`, one after another."""
    return "\n".join(re.findall(rf"^```{language}\n(.*?)^```", text, flags=re.MULTILINE | re.DOTALL))


class TheBlock(unittest.TestCase):
    def test_the_real_block_breaks_no_rule(self):
        self.assertEqual(runner.findings(RUNNER), [])

    def test_the_whole_contract_still_breaks_none_and_reports_this_block_by_name(self):
        self.assertEqual(consuming.findings(CONTRACT), [])
        broken = consuming.findings({**CONTRACT, runner.BLOCK: planted(docker_socket=True)})
        self.assertTrue(broken)
        self.assertTrue(all(finding.startswith(f"{runner.BLOCK}: ") for finding in broken), broken)

    def test_a_contract_with_no_runner_block_is_a_finding_rather_than_a_silence(self):
        self.assertIn("run shape is data, not prose", " ".join(runner.findings({})))

    def test_the_hole_the_editor_declared_is_filled_in_the_same_commit(self):
        """The editor's contract named this block in `not_yet_declared`; filling it removes the entry.

        ⚠️ This clause once also asserted that the OTHER hole that contract declared —
        what a tag promises — was still open. The versioning work filled it
        in the same change, so the list is now EMPTY and the assertion was inverted
        here rather than deleted: an empty list is a claim, and the contract
        backs it with `why_nothing_is_undeclared`.
        """
        holes = " ".join(CONTRACT["not_yet_declared"])
        self.assertNotIn("the runner image", holes)
        self.assertNotIn("the tagging scheme", holes)
        self.assertEqual(CONTRACT["not_yet_declared"], [], "a hole is named here, never left to be found")
        self.assertTrue(CONTRACT["why_nothing_is_undeclared"])
        self.assertGreater(CONTRACT["provides"], 1, "a block a consumer can read moves `provides` (R9)")

    def test_each_planted_defect_is_found(self):
        plants = {
            "docker_socket": (planted(docker_socket=True), "Docker socket is never mounted"),
            "a socket mount": (planted(**{"mounts.0.host_path": "/var/run/docker.sock"}),
                               "a mount names the Docker socket"),
            "the network is up": (planted(**{"network.mode": "bridge"}), "reaches off the machine"),
            "no network flag": (planted(**{"network.run_flag": ""}), "names no run flag"),
            "a published port": (planted(ports=[{"container": 8080, "host": 8080}]),
                                 "the runner publishes a port"),
            "runs as root": (planted(**{"runs_as.uid": 0}), "runs_as is root"),
            "no user value": (planted(**{"runs_as.run_value": ""}), "nothing to write after --user"),
            "the user is optional": (planted(**{"runs_as.required": False}),
                                     "a run without the flag is root"),
            "no user for PowerShell": (planted(**{"runs_as.powershell_run_value": ""}),
                                       "a consumer on Windows has nothing to write"),
            "a PowerShell user of root": (planted(**{"runs_as.powershell_run_value": "0:0"}),
                                          "is a substitution or root"),
            "a PowerShell substitution": (planted(**{"runs_as.powershell_run_value": "$(id -u)"}),
                                          "is a substitution or root"),
            "no compose value": (planted(**{"runs_as.compose_value": ""}),
                                 "compose cannot evaluate"),
            "the workspace is a tmpfs": (planted(**{"workspace.kind": "tmpfs"}),
                                         "the workspace is not a bind"),
            "a second bind": (planted(mounts=[*RUNNER["mounts"], {"container_path": "/home",
                                                                  "kind": "bind", "host_path": "~"}]),
                              "binds are declared"),
            "a bind off the workspace": (planted(**{"mounts.0.container_path": "/elsewhere"}),
                                         "is not the workspace"),
            "a bind docker may create": (planted(**{"mounts.0.must_exist_before_start": False}),
                                         "docker creates a missing one root-owned"),
            "a read-only bind": (planted(**{"mounts.0.read_only": True}),
                                 "a graded run writes its build output there"),
            "no init": (planted(**{"init.enabled": False}), "reaps nothing"),
            "a command on the run line": (planted(command=["bash"]),
                                          "exit before the first exec arrived"),
            "not detached": (planted(**{"run.detached": False}), "the run is not detached"),
            "no container name": (planted(**{"run.name_template": ""}), "names no container"),
            "required and defaulted": (planted(**{"environment.0.required": True}),
                                       "is required and defaulted"),
        }
        for name, (block, needle) in plants.items():
            with self.subTest(plant=name):
                found = runner.findings(block)
                self.assertTrue(found, "the planted block reported nothing")
                self.assertTrue(any(needle in finding for finding in found), found)


class TheRenderedLines(unittest.TestCase):
    """The run line and the exec line come from the block, and a broken block renders neither."""

    def test_the_documented_run_line_is_what_the_block_renders(self):
        self.assertEqual(documented("docker run"), runner.run_line(RUNNER),
                         "regenerate the README's line: python3 consuming/consuming.py --run-line")

    def test_the_documented_powershell_run_line_is_what_the_block_renders(self):
        """⭐ PowerShell has no `id`, and a Windows user no uid: its line substitutes nothing."""
        for text in (README, (ROOT / "docs" / "consuming.md").read_text(encoding="utf-8")):
            line = documented("docker run", fenced(text, "powershell"), continuation="`")
            self.assertEqual(line, runner.run_line(RUNNER, shell=runner.POWERSHELL))
            for posix in ("$(", "id -u", "\\"):
                self.assertNotIn(posix, line)

    def test_a_shell_this_renderer_does_not_know_is_refused(self):
        with self.assertRaises(runner.Refused):
            runner.run_line(RUNNER, shell="cmd")

    def test_the_documented_exec_line_is_what_the_block_renders(self):
        self.assertEqual(documented("docker exec"), runner.exec_line(RUNNER))

    def test_a_real_invocation_fills_every_placeholder_and_keeps_the_quoting(self):
        line = runner.run_line(RUNNER, name="sf-1", source_root="/somewhere/sources",
                               tag="an-image", user="4242:4242")
        self.assertEqual(
            line,
            'docker run -d --name sf-1 --init --network none --user "4242:4242" '
            '-v "/somewhere/sources:/work" an-image',
        )
        for placeholder in ("<source>", "<source root>", "<tag>", "$(id -u)"):
            self.assertNotIn(placeholder, line)

    def test_the_substitution_is_double_quoted_so_a_shell_still_evaluates_it(self):
        """Single quotes would ship `$(id -u)` to docker literally, and the run would be root."""
        self.assertTrue(RUNNER["runs_as"]["quote_in_shell"])
        self.assertIn('--user "$(id -u):$(id -g)"', runner.run_line(RUNNER))
        self.assertNotIn("'", runner.run_line(RUNNER))

    def test_a_real_exec_fills_the_directory_the_name_and_the_command(self):
        line = runner.exec_line(RUNNER, name="sf-1", directory="unit-3", command=["mvn", "-q", "test"])
        self.assertEqual(line, "docker exec -w /work/unit-3 sf-1 mvn -q test")

    def test_a_block_with_a_finding_renders_neither_line(self):
        for render in (runner.run_line, runner.exec_line):
            with self.subTest(render=render.__name__):
                with self.assertRaises(runner.Refused) as refusal:
                    render(planted(docker_socket=True))
                self.assertIn("Docker socket", str(refusal.exception))

    def test_moving_a_value_in_the_block_moves_the_line_with_it(self):
        moved = runner.run_line(planted(**{"mounts.0.container_path": "/elsewhere",
                                           "workspace.container_path": "/elsewhere"}))
        self.assertIn('-v "<source root>:/elsewhere"', moved)
        self.assertNotIn(":/work", moved)

    def test_the_cli_prints_the_run_line_and_checks_every_block(self):
        def cli(*argv):
            return subprocess.run([sys.executable, str(ROOT / "consuming" / "consuming.py"),
                                   "--root", str(ROOT), *argv],
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True)

        self.assertEqual(cli("--check").returncode, 0)
        printed = cli("--run-line")
        self.assertEqual(printed.returncode, 0, printed.stderr)
        self.assertEqual(printed.stdout.strip(), runner.run_line(RUNNER))
        windows = cli("--run-line", "--powershell")
        self.assertEqual(windows.returncode, 0, windows.stderr)
        self.assertEqual(windows.stdout.strip(), runner.run_line(RUNNER, shell=runner.POWERSHELL))


class TheBlockAgreesWithTheImage(unittest.TestCase):
    """Every value the block states about the runner image is read back out of the build."""

    def test_the_repository_and_the_build_command_are_the_runners_own(self):
        self.assertEqual(RUNNER["image"]["repository"], runner_plan.REPOSITORY)
        self.assertEqual(RUNNER["image"]["registry"]["namespace_env_var"], "TOOLCHAIN_NAMESPACE")
        for command in (RUNNER["image"]["built_by"], RUNNER["image"]["tag_from"]):
            self.assertTrue((ROOT / command[1]).is_file(), command)
            self.assertIn("--runtimes", command)
        self.assertIn("--print-tag", RUNNER["image"]["tag_from"])
        for label in RUNNER["image"]["labels"].values():
            self.assertIn(label, DOCKERFILE)

    def test_the_selectable_runtimes_are_every_pinned_one(self):
        """The editor drops what it cannot carry; the runner carries them all."""
        self.assertEqual(RUNNER["runtimes"]["selectable"], sorted(PINS["runtimes"]))
        self.assertEqual(RUNNER["runtimes"]["default_set"], [])

    def test_the_workspace_is_the_dockerfiles_workdir(self):
        self.assertIn(f"\nWORKDIR {RUNNER['workspace']['container_path']}\n", DOCKERFILE)
        self.assertEqual([mount["container_path"] for mount in RUNNER["mounts"]],
                         [RUNNER["workspace"]["container_path"]])

    def test_the_image_declares_no_user_which_is_why_the_flag_is_required(self):
        self.assertIsNone(re.search(r"^USER\b", DOCKERFILE, flags=re.MULTILINE))
        self.assertTrue(RUNNER["runs_as"]["required"])
        self.assertIsNone(RUNNER["runs_as"]["uid"])

    def test_the_home_it_declares_is_the_one_the_plan_chose(self):
        home = next(entry for entry in RUNNER["environment"] if entry["name"] == "HOME")
        self.assertEqual(home["default"], runner_plan.RUNNER_HOME)
        self.assertIn("ENV HOME=${RUNNER_HOME}", DOCKERFILE)

    def test_the_prime_root_and_seeds_are_the_plans_own(self):
        self.assertEqual(RUNNER["prime"]["root"], runner_plan.PRIME_ROOT)
        self.assertEqual(RUNNER["prime"]["seeds"], runner_plan.PRIME_SEEDS)

    def test_the_image_idles_on_its_own_cmd_and_publishes_nothing(self):
        cmd = json.loads(re.search(r"^CMD (\[.*\])$", DOCKERFILE, flags=re.MULTILINE)[1])
        self.assertEqual(cmd[0], "sleep")
        self.assertEqual(RUNNER["command"], [], "a run-line command would replace that CMD")
        self.assertIsNone(re.search(r"^EXPOSE\b", DOCKERFILE, flags=re.MULTILINE))
        self.assertEqual(RUNNER["ports"], [])

    def test_the_documented_line_still_passes_the_static_check_the_component_keeps(self):
        self.assertEqual(runner_plan.run_line_findings(README), [])


class TheDocument(unittest.TestCase):
    """It quotes the runner block instead of restating it, and every key it names exists."""

    def test_every_key_path_it_names_resolves_in_the_contract(self):
        paths = sorted(set(KEY_PATH.findall(DOCUMENT)))
        self.assertGreater(len(paths), 20, paths)
        for path in paths:
            with self.subTest(path=path):
                resolve(CONTRACT, path)

    def test_a_key_path_the_contract_does_not_carry_would_be_caught(self):
        with self.assertRaises(KeyError):
            resolve(CONTRACT, "runner.network.interface")

    def test_it_names_every_section_the_block_carries(self):
        for section in RUNNER:
            with self.subTest(section=section):
                self.assertIn(f"runner.{section}", DOCUMENT)

    def test_it_states_why_there_is_no_compose_file_for_this_image(self):
        section = DOCUMENT.split("## The runner image", 1)
        self.assertEqual(len(section), 2, "the runner is not documented")
        self.assertIn("no compose file here and that is deliberate", section[1])

    def test_the_readme_defers_to_the_block_rather_than_being_the_authority(self):
        self.assertIn("That line is not the authority", README)
        self.assertIn("consuming.json", README)
        self.assertIn("--run-line", README)


if __name__ == "__main__":
    unittest.main()
