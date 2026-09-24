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
import tempfile
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
TAG = EDITOR["image"]["tag"]
RUNNER_TAG = CONTRACT["runner"]["image"]["tag"]
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
            # ⚠️ BOTH keys are planted deliberately. The plant used to set `default`
            # alone and relied on environment.0 being a required entry; when the
            # PASSWORD entry was removed (user ruling 2026-09-22) environment.0
            # became a NOT-required one and the plant would have gone on passing
            # while planting nothing at all.
            "required and defaulted": (planted(**{"environment.0.required": True,
                                                  "environment.0.default": "letmein"}),
                                       "is required and defaulted"),
            "a read-only root": (planted(**{"filesystem.read_only_root": True}),
                                 "does not declare the root writable"),
            "a read-only root in the compose file": (planted(**{"filesystem.compose_value": True}),
                                                     "does not declare the root writable"),
            "nothing named writable": (planted(**{"filesystem.never_read_only": []}),
                                       "names no path that must never be mounted read-only"),
            "the primed caches mounted read-only": (planted(**{"mounts.0.container_path": "/opt/prime",
                                                               "mounts.0.read_only": True}),
                                                    "/opt must stay writable"),
            "a tag that may be mutated": (planted(**{"image.tag.mutated_in_place": True}),
                                          "never mutated in place"),
            "a scheme that drops a part": (planted(**{"image.tag.scheme": "{repository}:{set}-{arch}"}),
                                           "which the tag scheme does not name"),
            "a part nothing describes": (planted(**{"image.tag.parts": {}}),
                                         "does not say what it is"),
            "a command that prints no tag": (planted(**{"image.tag.computed_by": ["python3", "x.py"]}),
                                             "is not a command that prints a tag"),
            "nothing said to move a tag": (planted(**{"image.tag.moved_by": []}),
                                           "image.tag.moved_by is empty"),
            "an upgrade note that says nothing": (planted(**{"image.tag.upgrade.re_verify": []}),
                                                  "nothing to re-verify"),
            "no tag block at all": (planted(**{"image.tag": {}}), "a consumer pins a tag with nothing"),
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


class TheTaggingScheme(unittest.TestCase):
    """What a tag encodes, what moves it, and what a consumer pins.

    ⭐ The scheme is asserted against the tag the BUILD computes, not against a
    second copy of it: `editor.image.tag.scheme` is formatted with the parts and
    compared with `tag_for`'s own output, so a change to either side is RED.
    """

    ARCH = "amd64"
    PLATFORM = "linux/amd64"

    @classmethod
    def computed(cls, names, root: Path = ROOT) -> str:
        """The tag the build prints for that set, planned end to end and never Docker."""
        pins = runner_plan.load(root)
        runner = runner_plan.plan(pins, editor_plan.selection(pins, names), cls.PLATFORM,
                                  runner_plan.inputs_digest(root))
        return editor_plan.plan(pins, editor_plan.load(root), runner,
                                editor_plan.inputs_digest(root)).tag

    def tree(self) -> Path:
        """A copy of the build inputs alone, cleaned up with the test."""
        tree = Path(tempfile.mkdtemp(prefix="tc06-inputs-"))
        self.addCleanup(shutil.rmtree, tree, ignore_errors=True)
        for entry in TAG["build_inputs"]:
            source, target = ROOT / entry, tree / entry
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_file():
                shutil.copy2(source, target)
            else:
                shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
        return tree

    def test_the_scheme_is_the_tag_the_build_actually_computes(self):
        digest = editor_plan.inputs_digest(ROOT)
        formatted = TAG["scheme"].format(repository=EDITOR["image"]["repository"],
                                         set="java-maven", arch=self.ARCH, inputs=digest[:12])
        self.assertEqual(formatted, self.computed(("java", "maven")))

    def test_an_empty_set_is_the_word_the_parts_promise(self):
        self.assertIn("the word none", TAG["parts"]["set"])
        self.assertIn(f":none-{self.ARCH}-", self.computed(()))

    def test_the_declared_build_inputs_are_the_ones_the_digest_reads(self):
        reads = set(editor_plan.OWN_INPUTS) | set(runner_plan.INPUT_ROOTS)
        self.assertEqual(sorted(TAG["build_inputs"]), sorted(reads))
        for entry in TAG["build_inputs"]:
            self.assertTrue((ROOT / entry).exists(), entry)

    def test_a_pinned_version_bump_computes_a_new_tag_rather_than_mutating_one(self):
        """Acceptance: a toolchain version bump produces a NEW tag."""
        tree = self.tree()
        before = editor_plan.inputs_digest(tree)
        self.assertEqual(before, editor_plan.inputs_digest(ROOT), "the copy is not the same inputs")
        pins = json.loads((tree / "pins.json").read_text(encoding="utf-8"))
        pins["runtimes"]["java"]["version"] = pins["runtimes"]["java"]["version"] + ".1"
        (tree / "pins.json").write_text(json.dumps(pins), encoding="utf-8")
        after = editor_plan.inputs_digest(tree)
        self.assertNotEqual(before, after, "a version bump left the digest where it was")
        self.assertNotEqual(self.computed(("java", "maven"), tree), self.computed(("java", "maven")),
                            "the bumped checkout computes the tag the unbumped one does")
        self.assertEqual(before, editor_plan.inputs_digest(ROOT),
                         "the tag already pinned no longer names what it named")

    def test_the_consuming_half_is_no_build_input_so_moving_it_moves_no_tag(self):
        """`releases[0].moves_every_tag` is false, and this is why."""
        inputs = [ROOT / entry for entry in TAG["build_inputs"]]
        moved = ("consuming.json", "consuming/consuming.py", "docs/consuming.md",
                 "docs/compose.reference.yaml", "README.md", "tests/test_consuming.py",
                 "tests/test_consuming_image.py")
        for path in moved:
            where = ROOT / path
            with self.subTest(path=path):
                self.assertTrue(where.is_file(), path)
                self.assertFalse(any(where == entry or entry in where.parents for entry in inputs))
        self.assertIs(CONTRACT["releases"][0]["moves_every_tag"], False)

    # ------------------------------------------- the runner block
    def runner_tag(self, names, root: Path = ROOT) -> str:
        """The tag the RUNNER's own build prints, planned end to end and never Docker."""
        pins = runner_plan.load(root)
        return runner_plan.plan(pins, editor_plan.selection(pins, names), self.PLATFORM,
                                runner_plan.inputs_digest(root)).tag

    def test_the_runners_scheme_is_the_tag_its_own_build_computes(self):
        digest = runner_plan.inputs_digest(ROOT)
        formatted = RUNNER_TAG["scheme"].format(repository=CONTRACT["runner"]["image"]["repository"],
                                                set="java-maven", arch=self.ARCH, inputs=digest[:12])
        self.assertEqual(formatted, self.runner_tag(("java", "maven")))

    def test_the_runner_declares_the_two_input_roots_its_digest_reads(self):
        self.assertEqual(sorted(RUNNER_TAG["build_inputs"]), sorted(runner_plan.INPUT_ROOTS))
        self.assertLess(len(RUNNER_TAG["build_inputs"]), len(TAG["build_inputs"]),
                        "the editor folds the runner in and adds its own; the runner does not")
        self.assertNotIn("prime", RUNNER_TAG["build_inputs"],
                         "prime/ is folded into a PRIMED build's digest only")
        self.assertIs(CONTRACT["runner"]["prime"]["folded_into_tag"], True)

    def test_an_editor_only_change_moves_no_runner_tag(self):
        """The property both blocks' `not_moved_by` claims, measured both ways."""
        tree = self.tree()
        editor_before, runner_before = editor_plan.inputs_digest(tree), runner_plan.inputs_digest(tree)
        self.assertEqual((editor_before, runner_before),
                         (editor_plan.inputs_digest(ROOT), runner_plan.inputs_digest(ROOT)))

        pins = json.loads((tree / "editor-pins.json").read_text(encoding="utf-8"))
        pins["base"]["image"] = pins["base"]["image"] + "-moved"
        (tree / "editor-pins.json").write_text(json.dumps(pins), encoding="utf-8")
        self.assertNotEqual(editor_plan.inputs_digest(tree), editor_before, "the editor's tag did not move")
        self.assertEqual(runner_plan.inputs_digest(tree), runner_before,
                         "an editor-only change moved a runner tag")

        runtimes = json.loads((tree / "pins.json").read_text(encoding="utf-8"))
        runtimes["runtimes"]["java"]["version"] = runtimes["runtimes"]["java"]["version"] + ".1"
        (tree / "pins.json").write_text(json.dumps(runtimes), encoding="utf-8")
        self.assertNotEqual(runner_plan.inputs_digest(tree), runner_before,
                            "a runtime bump did not move the runner's tag")

    def test_the_runners_consuming_half_is_no_build_input_either(self):
        inputs = [ROOT / entry for entry in RUNNER_TAG["build_inputs"]]
        for path in ("consuming.json", "consuming/runner.py", "consuming/consuming.py",
                     "docs/consuming.md", "tests/test_consuming_runner.py"):
            where = ROOT / path
            with self.subTest(path=path):
                self.assertTrue(where.is_file(), path)
                self.assertFalse(any(where == entry or entry in where.parents for entry in inputs))

    def test_the_same_plants_are_caught_in_the_runners_block_and_named_as_its_own(self):
        """`_tag_findings` takes a BLOCK, so the runner inherits every clause."""
        plants = {
            "a tag that may be mutated": ({"mutated_in_place": True}, "never mutated in place"),
            "a scheme that drops a part": ({"scheme": "{repository}:{set}-{arch}"},
                                           "which the tag scheme does not name"),
            "a command that prints no tag": ({"computed_by": ["python3", "x.py"]},
                                             "is not a command that prints a tag"),
            "nothing said to move a tag": ({"moved_by": []}, "image.tag.moved_by is empty"),
            "an upgrade note that says nothing": ({"upgrade": {}}, "nothing to re-verify"),
        }
        for name, (change, needle) in plants.items():
            with self.subTest(plant=name):
                contract = copy.deepcopy(CONTRACT)
                contract["runner"]["image"]["tag"].update(change)
                found = [f for f in consuming.findings(contract) if needle in f]
                self.assertTrue(found, consuming.findings(contract))
                self.assertTrue(all(f.startswith("runner: ") for f in found),
                                f"the runner's finding is not named as the runner's: {found}")

    def test_two_declared_sets_are_two_tags_two_consumers_can_hold_at_once(self):
        """Acceptance: two consumers pin different tags simultaneously — the host half."""
        sets = (("java",), ("java", "maven"), ("gradle", "java"))
        tags = {names: self.computed(names) for names in sets}
        self.assertEqual(len(set(tags.values())), len(sets), tags)
        self.assertEqual(tags[("java", "maven")], self.computed(("maven", "java")),
                         "the set is sorted, so the order it was declared in is not part of the tag")
        with self.assertRaises(runner_plan.Refused):
            self.computed(("java", "maven", "java"))  # and a duplicate is refused, not quietly folded


class TheReleaseNotes(unittest.TestCase):
    """One entry per `provides`, newest first, each saying what to re-verify."""

    @staticmethod
    def with_releases(**changes) -> dict:
        contract = copy.deepcopy(CONTRACT)
        contract.update(changes)
        return contract

    def test_the_newest_entry_is_this_contracts_own(self):
        self.assertEqual(CONTRACT["releases"][0]["provides"], CONTRACT["provides"])
        for entry in CONTRACT["releases"]:
            with self.subTest(provides=entry["provides"]):
                self.assertTrue(entry["summary"] and entry["re_verify"])
                self.assertIn(entry["moves_every_tag"], (True, False))
                self.assertTrue(entry["measured"], "a tag claim is measured, never assumed")

    def test_this_releases_moves_every_tag_is_false_because_neither_half_is_a_build_input(self):
        """The newest release adds keys only; the claim is the property, not convenience."""
        newest = CONTRACT["releases"][0]
        self.assertIs(newest["moves_every_tag"], False)
        roots = set(EDITOR["image"]["tag"]["build_inputs"]) | set(RUNNER_TAG["build_inputs"])
        inputs = [ROOT / entry for entry in roots]
        changed = ("consuming.json", "consuming/consuming.py", "consuming/runner.py",
                   "docs/consuming.md", "docs/compose.reference.yaml", "README.md",
                   "tests/test_consuming.py", "tests/test_consuming_image.py",
                   "tests/test_consuming_runner.py")
        for path in changed:
            where = ROOT / path
            with self.subTest(path=path):
                self.assertTrue(where.is_file(), path)
                self.assertFalse(any(where == entry or entry in where.parents for entry in inputs))

    def test_one_entry_carries_both_halves_of_this_release(self):
        """The format is one entry per `provides`, NOT one per change (two converged into 2)."""
        converged = next(entry for entry in CONTRACT["releases"] if entry["provides"] == 2)
        self.assertIn("runner", converged["summary"])
        self.assertIn("tag", converged["summary"])
        self.assertIn("one entry per provides", TAG["upgrade"]["notes_per_release"])
        self.assertIn("one entry per provides", RUNNER_TAG["upgrade"]["notes_per_release"])

    def test_a_provides_bump_with_no_note_and_a_gap_are_both_found(self):
        plants = {
            "a bump with no note": (self.with_releases(provides=CONTRACT["provides"] + 1),
                                    "a bump with no upgrade note"),
            "no notes at all": (self.with_releases(releases=[]), "releases is empty"),
            "a gap": (self.with_releases(provides=3, releases=[{"provides": 3, "summary": "s",
                                                                "re_verify": ["r"], "moves_every_tag": True},
                                                               CONTRACT["releases"][0]]),
                      "not one entry per provides"),
            "an entry that says nothing": (self.with_releases(
                releases=[dict(CONTRACT["releases"][0], re_verify=[]), CONTRACT["releases"][1]]),
                "says nothing to re-verify"),
            "an entry that will not say": (self.with_releases(
                releases=[{k: v for k, v in CONTRACT["releases"][0].items() if k != "moves_every_tag"},
                          CONTRACT["releases"][1]]),
                "does not say whether it moved every tag"),
        }
        for name, (contract, needle) in plants.items():
            with self.subTest(plant=name):
                found = consuming.findings(contract)
                self.assertTrue(any(needle in finding for finding in found), found)


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
                                env={"PATH": "/usr/bin:/bin:/usr/local/bin", "EDITOR_IMAGE": "an-image"})
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

    def test_the_editors_prime_is_declared_as_the_runners_and_is_the_builds_own(self):
        """`editor.prime`: the flag its build takes, the seeds its Dockerfile warms, the tag it moves."""
        prime, runner = EDITOR["prime"], CONTRACT["runner"]["prime"]
        self.assertEqual(prime["declared_by"], runner["declared_by"], "one prime, one flag, both builds")
        self.assertIs(prime["folded_into_tag"], True)
        self.assertEqual(sorted(prime["seeds"]), sorted(editor_plan.prime_contract.TOOLS))
        for tool, seed in prime["seeds"].items():
            self.assertIn(f"/tmp/prime/{tool} {prime['root']}/{seed}", DOCKERFILE, tool)
        fixture = str(ROOT / "tests" / "fixtures" / "prime")
        flag = [fixture if part == "<directory>" else part for part in prime["declared_by"].split()]
        tag_from = ["gradle,java,maven" if part == "<the declared set>" else part for part in EDITOR["image"]["tag_from"]]
        unprimed, primed = (subprocess.run([sys.executable, *tag_from[1:], *extra], cwd=ROOT, text=True,
                                           capture_output=True, check=True).stdout.strip()
                            for extra in ((), flag))
        self.assertTrue(primed.startswith(f"{editor_plan.REPOSITORY}:gradle-java-maven-"), primed)
        self.assertNotEqual(primed, unprimed, "a prime handed to the declared flag moved no tag")

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
        # ⛔ THE FLAG AND THE BIND ARE ASSERTED TOGETHER, and that pairing is the
        # point. --auth=none is safe ONLY because the port is published on
        # loopback, so loosening either one alone must fail this test. An
        # ABSENT --auth is also refused: code-server defaults to password, so
        # omitting the flag is a different setting rather than this one.
        self.assertIn("--auth=none", command, "the auth mode is explicit, never left to the default")
        port = EDITOR["ports"][0]
        self.assertEqual(port["host_bind"], "127.0.0.1",
                         "an unauthenticated IDE may be published on loopback and nowhere else")
        self.assertFalse(port["publish_on_all_interfaces"],
                         "an unauthenticated IDE may be published on loopback and nowhere else")

    def test_the_workspace_trust_flag_is_in_the_images_cmd_as_well_as_the_contract(self):
        # ⛔ The Restricted Mode defect: the contract carried --disable-workspace-trust and the
        # image's CMD did not, so a consumer that did not copy the compose
        # template got a workbench in Restricted Mode and a lockdown that never
        # ran. ⚠️ Both halves are asserted, because the defect was the gap
        # between them.
        cmd = json.loads(re.search(r"^CMD (\[.*\])$", DOCKERFILE, flags=re.MULTILINE)[1])
        self.assertIn("--disable-workspace-trust", cmd)
        self.assertIn("--disable-workspace-trust", EDITOR["command"])
        self.assertIn("--disable-workspace-trust", EDITOR["command_notes"]["workspace_trust"])

    def test_the_extension_ids_are_the_lockdown_manifests_own(self):
        self.assertEqual(EDITOR["extensions"]["always_installed"], [LOCKDOWN.id])
        contributed = sorted(json.loads((ROOT / "lockdown" / "package.json").read_text(encoding="utf-8"))
                             ["contributes"]["configuration"]["properties"])
        self.assertEqual(EDITOR["extensions"]["settings_a_study_server_writes"], contributed)

    def test_the_entrypoint_repairs_the_uid_before_it_seeds_anything(self):
        """The uid ruling's mechanism: without this ordering a uid but 1000 has HOME=/ here."""
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

    def test_it_states_each_of_the_five_rulings_with_its_failure(self):
        rulings = ("Loopback-only port binding", "Mount only the sources",
                   "Run as the repository owner's uid:gid",
                   "A bind source must exist on the host before the container starts",
                   "The root filesystem stays writable")
        for ruling in rulings:
            with self.subTest(ruling=ruling):
                section = DOCUMENT.split(ruling, 1)
                self.assertEqual(len(section), 2, "the ruling is not stated")
                self.assertIn("The failure", section[1].split("\n### ", 1)[0])

    def test_it_states_the_tagging_scheme_with_a_worked_example(self):
        self.assertIn("## Versioning and pinning", DOCUMENT)
        self.assertIn(TAG["example"], DOCUMENT)
        worked = DOCUMENT.split("### Two consumers, two tags, at once", 1)
        self.assertEqual(len(worked), 2, "the worked example is not there")
        example = worked[1].split("\n### ", 1)[0]
        self.assertEqual(example.count("export EDITOR_IMAGE="), 2, "one consumer is not two")
        self.assertIn("--print-tag", example)

    def test_the_versioning_section_speaks_for_both_images(self):
        section = DOCUMENT.split("## Versioning and pinning", 1)
        self.assertEqual(len(section), 2)
        opening = section[1].split("\n### ", 1)[0]
        self.assertIn("runner.image.tag", opening, "the shared scheme names only one image")
        runner_section = DOCUMENT.split("### What the runner's tag promises", 1)
        self.assertEqual(len(runner_section), 2, "the runner's tag is not documented")
        self.assertIn(RUNNER_TAG["example"], runner_section[1])
        self.assertIn("moves no runner tag", DOCUMENT)

    def test_it_says_which_half_provides_versions_and_which_half_the_tag_does(self):
        self.assertIn("versioned by `provides`", DOCUMENT)
        self.assertIn("`releases`", DOCUMENT)
        for key in ("moved_by", "not_moved_by", "promises", "does_not_promise", "mutated_in_place"):
            with self.subTest(key=key):
                self.assertIn(f"editor.image.tag.{key}", DOCUMENT)

    def test_it_marks_the_fragment_a_template_and_forbids_reading_the_dockerfile(self):
        self.assertIn("TEMPLATE, not an include", DOCUMENT)
        self.assertIn("never reads the `Dockerfile`", DOCUMENT)

    def test_the_readme_sends_a_consumer_here_and_no_longer_defers_it(self):
        self.assertIn("docs/consuming.md", README)
        self.assertNotIn("which is a later task's", README)
        self.assertEqual(runner_plan.run_line_findings(README), [])

    def test_the_readme_sends_a_consumer_here_for_what_a_tag_promises_too(self):
        self.assertIn("Versioning and pinning", README)
        self.assertNotIn("belongs to the versioning task", DOCUMENT)
        self.assertNotIn("says nothing about what a tag promises",
                         "".join(CONTRACT["not_yet_declared"]))


if __name__ == "__main__":
    unittest.main()
