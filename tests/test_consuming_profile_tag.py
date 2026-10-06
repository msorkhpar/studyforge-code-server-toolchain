"""The contract's `profile_tag` block: it is checked, and the command it names answers for every profile.

Run from the component root: `python3 -m unittest tests.test_consuming_profile_tag -v`.
No Docker: the command prints a tag from the plan alone.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "consuming"))
import consuming  # noqa: E402

CONTRACT = consuming.load(ROOT)
BLOCK = CONTRACT["profile_tag"]
PLATFORM = "linux/amd64"
#: Profiles of both kinds, with the runtimes each layers on, read from the profile files.
PROFILES = {
    "jvm-frameworks": "legacy",
    "fixture-libs": "legacy",
    "fixture-packages": "packages",
    "claude-sdks": "packages",
}


def asked(profile: str, image: str, runtimes: str = "", *, command=None):
    slots = {"<profile>": profile, "<runner|editor>": image, "<the declared set>": runtimes,
             "<platform>": PLATFORM}
    argv = [slots.get(one, one) for one in (command or BLOCK["printed_by"])]
    argv[argv.index("python3")] = sys.executable
    return subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, stdin=subprocess.DEVNULL)


def plant(**changes) -> dict:
    contract = copy.deepcopy(CONTRACT)
    contract["profile_tag"].update(changes)
    return contract


class TheBlock(unittest.TestCase):
    def test_the_real_contract_has_no_finding(self):
        self.assertEqual(consuming.findings(CONTRACT), [])

    def test_each_plant_is_found(self):
        gone = {key: value for key, value in CONTRACT.items() if key != "profile_tag"}
        no_slot = [one for one in BLOCK["printed_by"] if one != "<platform>"]
        plants = {
            "no block": (gone, "profile_tag is absent"),
            "no slot": (plant(printed_by=no_slot), "names no <platform> slot"),
            "no tag flag": (plant(printed_by=[one for one in BLOCK["printed_by"] if one != "--print-tag"]),
                            "not a command that prints a tag"),
            "no api": (plant(profile_tag_api=None), "profile_tag_api is absent"),
            "docker not ruled out": (plant(runs_no_docker=False), "runs no docker"),
            "no refusal": (plant(refuses=""), "profile_tag.refuses is empty"),
        }
        for name, (contract, needle) in plants.items():
            with self.subTest(plant=name):
                self.assertTrue(any(needle in found for found in consuming.findings(contract)))

    def test_the_command_names_a_script_this_component_holds(self):
        self.assertTrue((ROOT / BLOCK["printed_by"][1]).is_file())


class TheCommand(unittest.TestCase):
    def test_it_prints_one_tag_line_for_both_kinds_and_both_images(self):
        for profile, kind in PROFILES.items():
            for image in ("runner", "editor"):
                with self.subTest(profile=profile, kind=kind, image=image):
                    done = asked(profile, image)
                    self.assertEqual(done.returncode, 0, done.stderr)
                    lines = done.stdout.splitlines()
                    self.assertEqual(len(lines), 1, done.stdout)
                    self.assertRegex(lines[0], rf"^code-server-toolchain/{image}-{profile}:[A-Za-z0-9_.-]+$")

    def test_a_profile_without_package_entries_has_the_tag_its_own_recipe_prints(self):
        for profile, kind in PROFILES.items():
            if kind != "legacy":
                continue
            with self.subTest(profile=profile):
                own = asked(profile, "runner", command=[
                    "python3", "docker/profile/profile_build.py", "--profile", "<profile>",
                    "--image", "<runner|editor>", "--runtimes", "<the declared set>", "--print-tag",
                    "--platform", "<platform>"])
                self.assertEqual(asked(profile, "runner").stdout, own.stdout)

    def test_a_profile_it_does_not_have_is_refused_on_stderr_alone(self):
        done = asked("no-such-profile", "runner")
        self.assertEqual((done.returncode, done.stdout), (2, ""))
        self.assertIn("refused", done.stderr)


if __name__ == "__main__":
    unittest.main()
