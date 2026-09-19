"""The editor's toolchain SELECTION (TC-02) — no Docker needed.

Run from the component root: `python3 -m unittest discover -s tests -v`.
Every clause is asserted BOTH ways: the declared runtimes are present, and an
undeclared one leaves no tree, `PATH` entry, `JAVA_HOME`, extension or setting.
The image tests (`tests/test_editor_selection_image.py`) read the same clauses
off built images.
"""

from __future__ import annotations

import copy
import itertools
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDITOR = ROOT / "docker" / "editor"
sys.path.insert(0, str(EDITOR))

import editor_plan  # noqa: E402

runner_plan = editor_plan.runner_plan

PINS = runner_plan.load(ROOT)
EPINS = editor_plan.load(ROOT)
DIGEST = "0" * 64
DOCKERFILE = (ROOT / editor_plan.DOCKERFILE).read_text(encoding="utf-8")
SEED = EDITOR / "seed" / "settings.json"
#: TC-01's image, as its Dockerfile wrote PATH for the constant five.
TC01_PATH = ("/opt/java/openjdk/bin:/opt/maven/bin:/opt/gradle/bin:/opt/kotlinc/bin:/opt/node/bin:"
             "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
#: The lockdown extension: no runtime's, so every set installs it (TC-04).
LOCKDOWN = editor_plan.lockdown_identity(ROOT)


def planned(names, epins: dict = EPINS, pins: dict = PINS) -> editor_plan.EditorPlan:
    runner = runner_plan.plan(pins, editor_plan.selection(pins, names), "linux/amd64", DIGEST)
    return editor_plan.plan(pins, epins, runner, DIGEST)


def carried_sets():
    """Every set the editor builds: each subset of the carried runtimes the runner accepts."""
    carried = sorted(set(PINS["runtimes"]) - set(editor_plan.NOT_CARRIED))
    for size in range(len(carried) + 1):
        for names in itertools.combinations(carried, size):
            if all(set(PINS["runtimes"][n].get("requires", [])) <= set(names) for n in names):
                yield names


def check_names(built: editor_plan.EditorPlan) -> set[str]:
    return {line.split("|", 1)[0] for line in built.build_args["CHECKS"].splitlines()}


def cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    """build.py with no Docker on PATH: anything it refuses, it refuses before Docker starts."""
    env = {"PATH": "/nonexistent", "PYTHONDONTWRITEBYTECODE": "1"}
    command = [sys.executable, str(root / "docker" / "editor" / "build.py"), "--root", str(root), *args]
    return subprocess.run(command, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)


class TheJavaMavenSet(unittest.TestCase):
    def test_java_and_maven_build_only_their_own_trees_checks_and_extensions(self):
        built = planned(["java", "maven"])
        self.assertEqual(built.names, ("java", "maven"))
        self.assertEqual(check_names(built), {"java", "maven"})
        self.assertEqual(built.build_args["OPT_EXPECTED"].split(), ["code-server", "java", "maven", "maven-repo"])
        java = [e for e in EPINS["extensions"] if EPINS["extensions"][e]["for"] == "java"]
        self.assertEqual(built.build_args["EXPECTED_EXTENSIONS"].split(),
                         sorted([f"{e}@{EPINS['extensions'][e]['version']}" for e in java] + [LOCKDOWN.expected]))
        self.assertEqual((built.build_args["WITH_TYPESCRIPT"], built.build_args["WITH_READLINE"]), ("no", "no"))
        self.assertNotIn("typescript.tgz", built.build_args["FETCH"])
        self.assertRegex(built.tag, r"^code-server-toolchain/editor:java-maven-amd64-0{12}$")
        self.assertEqual(built.build_args["RUNNER_IMAGE"],
                         runner_plan.tag_for(("java", "maven"), "amd64", DIGEST))

    def test_every_selected_toolchain_is_checked_for_its_pinned_version_and_no_other_is(self):
        for names in carried_sets():
            with self.subTest(names=names):
                built = planned(names)
                expected = set(names) | ({"typescript"} if "node" in names else set())
                self.assertEqual(check_names(built), expected)
                lines = built.build_args["CHECKS"].splitlines()
                for name in names:
                    for check in PINS["runtimes"][name]["checks"]:
                        expect = check["expect"].format(version=PINS["runtimes"][name]["version"])
                        self.assertIn(f"{name}|{check['command']}|{expect}", lines)


class TheDefaultSet(unittest.TestCase):
    def test_the_default_is_tc01s_five_with_every_pin_and_only_the_absent_maven_entry_dropped(self):
        built = planned(editor_plan.DEFAULT_SET)
        self.assertEqual(built.names, ("gradle", "java", "kotlin", "node", "python"))
        self.assertEqual(built.build_args["EXPECTED_EXTENSIONS"].split(),
                         sorted([f"{e}@{EPINS['extensions'][e]['version']}" for e in EPINS["extensions"]]
                                + [LOCKDOWN.expected]))
        self.assertEqual((built.build_args["WITH_TYPESCRIPT"], built.build_args["WITH_READLINE"]), ("yes", "yes"))
        self.assertEqual(built.build_args["EDITOR_PATH"], TC01_PATH.replace("/opt/maven/bin:", ""))
        self.assertEqual(built.build_args["SEED_DROP"], "")
        self.assertIn("export JAVA_HOME=/opt/java/openjdk", built.build_args["PROFILE_D"])

    def test_the_cli_builds_the_default_set_when_none_is_declared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = TheRefusals.copy(tmp)
            default = cli(root, "--print-tag")
            declared = cli(root, "--print-tag", "--runtimes", ",".join(editor_plan.DEFAULT_SET))
            other = cli(root, "--print-tag", "--runtimes", "java,maven")
        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertEqual(default.stdout, declared.stdout)
        self.assertIn(":gradle-java-kotlin-node-python-", default.stdout)
        self.assertIn(":java-maven-", other.stdout)


class TheRefusals(unittest.TestCase):
    @staticmethod
    def copy(tmp: str) -> Path:
        root = Path(tmp)
        for name in ("pins.json", "editor-pins.json"):
            shutil.copy(ROOT / name, root / name)
        shutil.copytree(ROOT / "docker", root / "docker", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "prime", root / "prime", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "lockdown", root / "lockdown", ignore=shutil.ignore_patterns("__pycache__"))
        return root

    def test_an_unpinned_toolchain_is_refused_naming_it_and_what_is_pinned(self):
        with self.assertRaises(editor_plan.Refused) as refused:
            editor_plan.selection(PINS, ["java", "cobol"])
        self.assertIn("'cobol'", str(refused.exception))
        self.assertIn(str(sorted(PINS["runtimes"])), str(refused.exception))
        self.assertEqual(editor_plan.selection(PINS, ["java", "maven"]), ["java", "maven"])

    def test_a_name_not_shaped_like_a_runtime_id_is_refused_and_never_echoed(self):
        for name in ("../etc", "Java", "a" * 40, "java maven"):
            with self.subTest(name=name):
                with self.assertRaises(editor_plan.Refused) as refused:
                    editor_plan.selection(PINS, ["java", name])
                self.assertNotIn(name, str(refused.exception))

    def test_the_build_refuses_an_unpinned_toolchain_before_docker_starts_and_builds_a_pinned_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.copy(tmp)
            refused = cli(root, "--runtimes", "java,cobol")
            self.assertEqual(refused.returncode, 2, refused.stderr)
            self.assertIn("'cobol'", refused.stderr)
            self.assertNotIn("Traceback", refused.stderr)
            accepted = cli(root, "--runtimes", "java,maven", "--print-tag")
            self.assertEqual(accepted.returncode, 0, accepted.stderr)

    def test_a_runtime_the_editor_cannot_carry_is_refused_naming_it_and_why(self):
        for name in editor_plan.NOT_CARRIED:
            with self.subTest(runtime=name):
                self.assertIn(name, PINS["runtimes"], "only a pinned runtime is ever listed as not carried")
                with self.assertRaises(editor_plan.Refused) as refused:
                    planned(["shell", name])
                self.assertIn(f"'{name}'", str(refused.exception))
                self.assertIn("/usr/local", str(refused.exception))
                runner = runner_plan.plan(PINS, [name], "linux/amd64", DIGEST)
                with self.assertRaises(editor_plan.Refused):
                    editor_plan.plan(PINS, EPINS, runner, DIGEST)
        self.assertEqual(planned(["shell"]).names, ("shell",))

    def test_a_build_tool_without_java_is_still_refused_by_the_runners_rule(self):
        with self.assertRaises(editor_plan.Refused):
            planned(["maven"])


class TheEnvironment(unittest.TestCase):
    """TC-01/16: `JAVA_HOME` and every /opt `PATH` entry name ONLY a declared runtime."""

    def test_path_and_java_home_follow_the_set_both_ways_for_every_carried_set(self):
        for names in carried_sets():
            with self.subTest(names=names):
                args = planned(names).build_args
                on_path = [p for p in args["EDITOR_PATH"].split(":") if p.startswith("/opt/")]
                self.assertEqual(on_path, [p for n, p in editor_plan.PATH_DIRS if n in names])
                self.assertTrue(args["EDITOR_PATH"].endswith(editor_plan.BASE_PATH))
                profile = re.search(r"^export PATH=(\S+):\$PATH$", args["PROFILE_D"], re.M)
                self.assertEqual(profile.group(1).split(":") if profile else [], on_path)
                has_java = "java" in names
                self.assertEqual(args["WITH_JAVA"], "yes" if has_java else "no")
                self.assertEqual("JAVA_HOME" in args["PROFILE_D"], has_java)

    def test_each_path_entry_is_inside_a_tree_the_runner_places_for_that_runtime(self):
        for name, path in editor_plan.PATH_DIRS:
            with self.subTest(runtime=name):
                self.assertIn(path.split("/")[2], runner_plan.OPT_DIRS[name])
        self.assertTrue(editor_plan.JAVA_HOME.startswith("/opt/" + runner_plan.OPT_DIRS["java"][0] + "/"))

    def test_the_dockerfile_takes_java_home_only_from_the_java_stage(self):
        self.assertEqual(DOCKERFILE.count("ENV JAVA_HOME="), 1)
        java = DOCKERFILE.split("AS home-java-yes", 1)[1].split("FROM ", 1)[0]
        self.assertIn("ENV JAVA_HOME=${JAVA_HOME_DIR}", java)
        self.assertIn("FROM home-java-${WITH_JAVA} AS editor", DOCKERFILE)
        self.assertEqual(runner_plan.dockerfile_findings(DOCKERFILE), [])


class TheExtensions(unittest.TestCase):
    def test_every_carried_set_installs_exactly_the_extensions_for_its_runtimes(self):
        for names in carried_sets():
            with self.subTest(names=names):
                expected = sorted([f"{e}@{v['version']}" for e, v in EPINS["extensions"].items()
                                   if v["for"] in names] + [LOCKDOWN.expected])
                self.assertEqual(sorted(planned(names).build_args["EXPECTED_EXTENSIONS"].split()), expected)

    def test_every_extension_names_a_pinned_runtime_and_a_planted_one_is_refused_naming_it(self):
        self.assertEqual(editor_plan.pins_findings(EPINS), [])
        planted = copy.deepcopy(EPINS)
        planted["extensions"]["fwcd.kotlin"]["for"] = "cobol"
        with self.assertRaises(editor_plan.Refused) as refused:
            planned(["java"], epins=planted)
        self.assertIn("fwcd.kotlin", str(refused.exception))
        planted["extensions"]["fwcd.kotlin"].pop("for")
        self.assertNotEqual(editor_plan.pins_findings(planted), [])

    def test_a_required_extension_pinned_for_another_runtime_is_refused_naming_it(self):
        planted = copy.deepcopy(EPINS)
        planted["extensions"]["redhat.java"]["for"] = "node"
        with self.assertRaises(editor_plan.Refused) as refused:
            planned(["java"], epins=planted)
        self.assertIn("redhat.java", str(refused.exception))
        planned(["node"], epins=planted)  # a set without java does not require it

    def test_a_dependency_outside_the_selection_is_refused_even_when_pinned(self):
        planted = copy.deepcopy(EPINS)
        planted["extensions"]["ms-python.debugpy"]["for"] = "node"
        with self.assertRaises(editor_plan.Refused) as refused:
            planned(["node"], epins=planted)
        self.assertIn("ms-python.python", str(refused.exception))


class TheSeed(unittest.TestCase):
    """The Dockerfile's own seed step, run by the host's `sh` and `sed` on a copy."""

    SCRIPT = re.search(r"RUN (for name in \$\{SEED_DROP\}; do \\\n.*?done) \\\n", DOCKERFILE, re.S).group(1)

    def seeded(self, drop: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            shutil.copy(SEED, path)
            script = self.SCRIPT.replace("${SEED_DROP}", drop).replace("/opt/code-server/seed/settings.json", str(path))
            ran = subprocess.run(["sh", "-c", script], capture_output=True, text=True, stdin=subprocess.DEVNULL)
            self.assertEqual(ran.returncode, 0, ran.stderr)
            return json.loads(re.sub(r"^\s*//.*$", "", path.read_text(encoding="utf-8"), flags=re.M))

    def test_the_seeds_blocks_are_exactly_the_declared_seed_runtimes(self):
        text = SEED.read_text(encoding="utf-8")
        self.assertEqual(tuple(re.findall(r"^\s*// @runtime (\S+)$", text, re.M)), editor_plan.SEED_RUNTIMES)
        self.assertEqual(tuple(re.findall(r"^\s*// @end (\S+)$", text, re.M)), editor_plan.SEED_RUNTIMES)

    def test_each_block_is_kept_exactly_when_its_runtime_is_declared(self):
        for names in carried_sets():
            drop = planned(names).build_args["SEED_DROP"]
            with self.subTest(names=names):
                keys = set(self.seeded(drop))
                for runtime in editor_plan.SEED_RUNTIMES:
                    self.assertEqual(any(k.startswith(f"{runtime}.") for k in keys), runtime in names)
                self.assertIn("terminal.integrated.defaultProfile.linux", keys)


class TheReadme(unittest.TestCase):
    def test_the_readme_documents_the_selection_and_what_the_editor_cannot_carry(self):
        section = (ROOT / "README.md").read_text(encoding="utf-8").split("## The editor image", 1)[1]
        section = section.split("\n## ", 1)[0]
        self.assertIn("--runtimes java,maven", section)
        for name in editor_plan.NOT_CARRIED:
            self.assertIn(f"`{name}`", section)


if __name__ == "__main__":
    unittest.main()
