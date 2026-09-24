"""The build plan, the pin file and the static checks — no Docker needed.

Run from the component root: `python3 -m unittest discover -s tests -v`.
Every rule is asserted BOTH ways: the real file passes, and a planted
violation is caught.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "docker" / "minimal"))
sys.path.insert(0, str(ROOT / "prime"))

import build  # noqa: E402
import build_inputs  # noqa: E402
import plan  # noqa: E402
import prime as prime_contract  # noqa: E402
import verify_repo  # noqa: E402

PINS = plan.load(ROOT)
FIXTURE = ROOT / "tests" / "fixtures" / "prime"
AMD64 = "linux/amd64"
DIGEST = "0" * 64
DOCKERFILE = (ROOT / plan.DOCKERFILE).read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
SMOKE = ROOT / "docker" / "minimal" / "smoke"


class TheDeclaredSet(unittest.TestCase):
    def test_a_pinned_set_is_planned(self):
        built = plan.plan(PINS, ["maven", "java"], AMD64, DIGEST)
        self.assertEqual(built.names, ("java", "maven"))
        self.assertEqual(built.build_args["WITH_MAVEN"], "yes")
        self.assertEqual(built.build_args["WITH_NODE"], "no")

    def test_an_unpinned_runtime_id_is_refused_naming_it_and_what_is_pinned(self):
        with self.assertRaises(plan.Refused) as caught:
            plan.plan(PINS, ["java", "cobol"], AMD64, DIGEST)
        message = str(caught.exception)
        self.assertIn("'cobol'", message, "a well-formed unpinned id is named")
        self.assertIn(str(sorted(PINS["runtimes"])), message)
        self.assertNotIn("'java'", message.split(";")[0], "only the unpinned id is named as unpinned")
        self.assertEqual(plan.plan(PINS, ["java"], AMD64, DIGEST).names, ("java",))

    def test_a_name_not_shaped_like_a_runtime_id_is_refused_and_never_echoed(self):
        for name in ("../etc", "Java", "a" * 40, "java maven", "cobol;rm", "-x", ""):
            with self.subTest(name=name):
                with self.assertRaises(plan.Refused) as caught:
                    plan.plan(PINS, ["java", name], AMD64, DIGEST)
                message = str(caught.exception)
                self.assertIn(str(sorted(PINS["runtimes"])), message)
                if name:
                    self.assertNotIn(name, message, "a malformed name is never echoed")
        # The boundary, the other way: the longest id shape is well-formed, so it is named.
        with self.assertRaises(plan.Refused) as caught:
            plan.plan(PINS, ["a" * 32], AMD64, DIGEST)
        self.assertIn("a" * 32, str(caught.exception))

    def test_the_runner_and_the_editor_accept_the_same_id_shape(self):
        editor = (ROOT / "docker" / "editor" / "editor_plan.py").read_text(encoding="utf-8")
        shape = re.search(r'^_NAME = re\.compile\(r"(?P<p>[^"]+)"\)$', editor, re.M)
        self.assertIsNotNone(shape, "the editor's id shape is where its selection code put it")
        self.assertEqual(shape.group("p"), plan.NAME.pattern)

    def test_the_build_names_an_unpinned_id_before_docker_starts(self):
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        command = [sys.executable, str(ROOT / "docker" / "minimal" / "build.py"), "--platform", AMD64, "--print-tag"]
        refused = subprocess.run(command + ["--runtimes", "java,cobol"], env=env, capture_output=True,
                                 text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(refused.returncode, 2, refused.stderr)
        self.assertIn("'cobol'", refused.stderr)
        self.assertNotIn("Traceback", refused.stderr)
        malformed = subprocess.run(command + ["--runtimes", "java,../etc"], env=env, capture_output=True,
                                   text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(malformed.returncode, 2, malformed.stderr)
        self.assertNotIn("../etc", malformed.stderr)
        accepted = subprocess.run(command + ["--runtimes", "java"], env=env, capture_output=True,
                                  text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

    def test_a_duplicate_is_refused(self):
        with self.assertRaises(plan.Refused):
            plan.plan(PINS, ["java", "java"], AMD64, DIGEST)

    def test_a_build_tool_without_java_is_refused_and_with_it_is_not(self):
        for tool in ("maven", "gradle", "kotlin"):
            with self.subTest(tool=tool):
                with self.assertRaises(plan.Refused):
                    plan.plan(PINS, [tool], AMD64, DIGEST)
                plan.plan(PINS, [tool, "java"], AMD64, DIGEST)

    def test_an_empty_set_is_a_plan_with_nothing_in_it(self):
        built = plan.plan(PINS, [], AMD64, DIGEST)
        self.assertTrue(all(built.build_args[f"WITH_{n}"] == "no" for n in ("JAVA", "MAVEN", "NODE", "PYTHON")))


class ThePlatform(unittest.TestCase):
    def test_both_recorded_architectures_plan_and_pick_their_own_archive(self):
        for platform, arch in (("linux/amd64", "amd64"), ("linux/arm64", "arm64")):
            built = plan.plan(PINS, ["node"], platform, DIGEST)
            self.assertEqual(built.build_args["NODE_URL"], PINS["runtimes"]["node"]["archives"][arch]["url"])
            self.assertEqual(built.build_args["NODE_SHA256"], PINS["runtimes"]["node"]["archives"][arch]["sha256"])

    def test_any_other_platform_is_refused_by_name(self):
        with self.assertRaises(plan.Refused) as caught:
            plan.plan(PINS, ["shell"], "linux/riscv64", DIGEST)
        self.assertIn(str(sorted(PINS["platforms"])), str(caught.exception))


class OneVersionPlace(unittest.TestCase):
    def test_every_check_carries_the_pinned_version(self):
        built = plan.plan(PINS, sorted(PINS["runtimes"]), AMD64, DIGEST)
        for name, entry in PINS["runtimes"].items():
            if "{version}" in entry["checks"][0]["expect"]:
                self.assertIn(f"{name}|", built.build_args["CHECKS"])
                self.assertIn(entry["version"], built.build_args["CHECKS"])

    def test_python_arrives_as_the_base_only_when_declared(self):
        python = f"{PINS['runtimes']['python']['image']}@{PINS['runtimes']['python']['digest']}"
        base = f"{PINS['base']['image']}@{PINS['base']['digest']}"
        self.assertEqual(plan.plan(PINS, ["python"], AMD64, DIGEST).build_args["RUNNER_BASE"], python)
        self.assertEqual(plan.plan(PINS, ["shell"], AMD64, DIGEST).build_args["RUNNER_BASE"], base)

    def test_the_plan_supplies_exactly_the_args_the_dockerfile_declares(self):
        declared = set(re.findall(r"^\s*ARG\s+(\w+)", DOCKERFILE, re.M))
        supplied = set(plan.plan(PINS, sorted(PINS["runtimes"]), AMD64, DIGEST).build_args)
        self.assertEqual(declared - supplied, set(), "an ARG nothing supplies would build empty")
        self.assertEqual(supplied - declared, set(), "an argument no ARG reads is a pin that pins nothing")


class ThePinFile(unittest.TestCase):
    def test_the_real_pins_are_well_formed(self):
        self.assertEqual(plan.pins_findings(PINS), [])

    def test_each_planted_defect_is_found(self):
        plants = {
            "a tag without a digest": lambda p: p["runtimes"]["java"].update(digest="25-jdk"),
            "an archive without a checksum": lambda p: p["runtimes"]["gradle"]["archives"]["any"].update(sha256=""),
            "a pin without its source": lambda p: p["runtimes"]["maven"].update(sources=[]),
            "single-source without saying why": lambda p: p["runtimes"]["kotlin"].pop("why_single"),
            "a runtime nobody version-checks": lambda p: p["runtimes"]["node"].update(checks=[]),
        }
        for label, mutate in plants.items():
            with self.subTest(plant=label):
                planted = copy.deepcopy(PINS)
                mutate(planted)
                self.assertNotEqual(plan.pins_findings(planted), [])

    def test_every_pin_says_where_it_came_from(self):
        entries = [PINS["base"], *PINS["runtimes"].values(), PINS["runtimes"]["maven"]["warm"]]
        for entry in entries:
            self.assertTrue(entry["sources"] and all(s["host"] and s["taken"] for s in entry["sources"]))

    def test_the_maven_warm_is_recorded(self):
        files = PINS["runtimes"]["maven"]["warm"]["files"]
        self.assertTrue(any(name.endswith(".jar") for name in files))
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{64}", value) for value in files.values()))


class TheTag(unittest.TestCase):
    def test_the_tag_is_order_free_and_moves_with_the_inputs(self):
        first = plan.plan(PINS, ["maven", "java"], AMD64, "a" * 64).tag
        self.assertEqual(first, plan.plan(PINS, ["java", "maven"], AMD64, "a" * 64).tag)
        self.assertNotEqual(first, plan.plan(PINS, ["java", "maven"], AMD64, "b" * 64).tag)
        self.assertNotEqual(first, plan.plan(PINS, ["java", "maven"], "linux/arm64", "a" * 64).tag)

    def test_the_inputs_digest_moves_when_an_input_changes(self):
        with tempfile.TemporaryDirectory() as scratch:
            copy_root = build_inputs.copy_inputs(scratch, inputs=plan.INPUT_ROOTS)
            before = plan.inputs_digest(copy_root)
            self.assertEqual(before, plan.inputs_digest(ROOT))
            (copy_root / "docker" / "minimal" / "Dockerfile").write_text(DOCKERFILE + "\n# planted\n")
            self.assertNotEqual(before, plan.inputs_digest(copy_root))


class TheDockerfile(unittest.TestCase):
    def test_the_real_dockerfile_chooses_nothing(self):
        self.assertEqual(plan.dockerfile_findings(DOCKERFILE), [])

    def test_a_planted_default_is_found(self):
        self.assertNotEqual(plan.dockerfile_findings(DOCKERFILE + "\nARG NODE_VERSION=24\n"), [])

    def test_a_planted_literal_image_is_found(self):
        self.assertNotEqual(plan.dockerfile_findings(DOCKERFILE + "\nFROM node:24 AS extra\n"), [])

    def test_a_planted_bare_scratch_stage_is_found_and_the_real_no_stages_are_not_bare(self):
        """A bare `-no` stage let a `python` build hold every runtime."""
        for name in ("java", "maven", "mavenrepo", "gradle", "kotlin", "node"):
            with self.subTest(stage=f"{name}-no"):
                stage = f"FROM scratch AS {name}-no\nWORKDIR /opt\n"
                self.assertIn(stage, DOCKERFILE)
                planted = DOCKERFILE.replace(stage, f"FROM scratch AS {name}-no\n")
                self.assertTrue(any("bare" in f for f in plan.dockerfile_findings(planted)))
        self.assertNotEqual(plan.dockerfile_findings(DOCKERFILE + "\nFROM scratch AS last\n"), [])

    def test_the_runner_reads_its_cache_key_before_it_copies_any_selected_stage(self):
        """Every layer the runner copies a selection into is cached per image tag."""
        runner = DOCKERFILE[DOCKERFILE.index("FROM ${RUNNER_BASE} AS runner"):]
        keyed = runner.index('RUN : "runner ${CACHE_KEY}"')
        self.assertLess(runner.index("ARG CACHE_KEY"), keyed)
        self.assertLess(keyed, runner.index("COPY --from="))
        self.assertEqual(plan.keyed_copy_findings(DOCKERFILE), [])

    def test_a_selected_stage_copied_before_the_cache_key_is_found_each_way_it_can_be_planted(self):
        """The other way: the unkeyed runner and an unkeyed selected copy elsewhere are named."""
        key = 'ARG CACHE_KEY\nRUN : "runner ${CACHE_KEY}"\n'
        self.assertIn(key, DOCKERFILE)
        selected = ("java", "maven", "mavenrepo", "gradle", "kotlin", "node")
        plants = {
            "the key removed": (DOCKERFILE.replace(key, ""), selected),
            "the key below the first COPY": (
                DOCKERFILE.replace(key, "").replace("COPY --from=java / /\n", "COPY --from=java / /\n" + key, 1),
                ("java",)),
            "maven-fetch copying the selection": (
                DOCKERFILE.replace("COPY --from=java-yes / /", "COPY --from=java / /"), ("java",)),
        }
        for label, (planted, named) in plants.items():
            with self.subTest(plant=label):
                self.assertNotEqual(planted, DOCKERFILE)
                found = plan.keyed_copy_findings(planted)
                self.assertEqual(sorted(re.findall(r"COPY --from=(\S+) copies", " ".join(found))), sorted(named))
                self.assertEqual([f for f in plan.dockerfile_findings(planted) if "another selection's layer" in f], found)

    def test_the_cache_key_is_the_tag_so_it_moves_with_the_set_and_the_inputs(self):
        built = plan.plan(PINS, ["python"], AMD64, DIGEST)
        self.assertEqual(built.build_args["CACHE_KEY"], built.tag)
        others = [plan.plan(PINS, ["gradle", "java", "kotlin", "node", "python"], AMD64, DIGEST),
                  plan.plan(PINS, ["python"], AMD64, "1" * 64), plan.plan(PINS, ["python"], "linux/arm64", DIGEST)]
        for other in others:
            with self.subTest(other=other.tag):
                self.assertNotEqual(other.build_args["CACHE_KEY"], built.build_args["CACHE_KEY"])

    def test_the_opt_directories_are_exactly_the_dockerfiles_copy_destinations(self):
        copied = set(re.findall(r"^COPY --from=\S+ \S+ /opt/([\w-]+)(?:/\S*)?$", DOCKERFILE, re.M))
        self.assertEqual(copied, {d for dirs in plan.OPT_DIRS.values() for d in dirs})
        self.assertLessEqual(set(plan.OPT_DIRS), set(PINS["runtimes"]))

    def test_each_set_expects_exactly_its_own_opt_directories(self):
        expected = {
            ("python",): "", ("shell",): "", ("sqlite",): "", ("node",): "node", ("java",): "java",
            ("java", "maven"): "java maven maven-repo", ("gradle", "java"): "gradle java",
            ("java", "kotlin"): "java kotlinc",
        }
        for names, opt in expected.items():
            with self.subTest(names=names):
                self.assertEqual(plan.plan(PINS, list(names), AMD64, DIGEST).build_args["OPT_EXPECTED"], opt)
        self.assertEqual(set(n for names in expected for n in names), set(PINS["runtimes"]),
                         "every runtime in the vocabulary is named")

    def test_no_editor_is_named(self):
        for word in ("code-server", "--install-extension", "EXPOSE"):
            self.assertNotIn(word, "\n".join(l for l in DOCKERFILE.splitlines() if not l.lstrip().startswith("#")))


class TheCorpusPrime(unittest.TestCase):
    """A corpus's practice dependencies are warmed INTO the runner, or nothing is."""

    @staticmethod
    def projects(*keep: str) -> Path:
        """A prime directory holding only the fixture projects named."""
        target = Path(tempfile.mkdtemp()) / "prime"
        for name in keep:
            shutil.copytree(FIXTURE / name, target / name)
        return target

    def built(self, *keep: str, names=("gradle", "java", "maven")):
        prime = self.projects(*keep) if keep else None
        try:
            return build.planned(ROOT, AMD64, list(names), prime)
        finally:
            if prime is not None:
                shutil.rmtree(prime.parent, ignore_errors=True)

    def test_a_corpus_with_no_declared_dependency_is_untouched(self):
        """The other way, and the one every corpus gets today: no seed, no /opt entry, no argument."""
        args = self.built().build_args
        self.assertEqual([args["WITH_GRADLE_PRIME"], args["WITH_MAVEN_PRIME"]], ["no", "no"])
        self.assertEqual(args["PRIME_MAVEN_ARGS"], "")
        self.assertEqual(args["PRIME_GRADLE_HOME"], f"{plan.RUNNER_HOME}/.gradle")
        self.assertNotIn("prime", args["OPT_EXPECTED"].split())

    def test_each_declared_tool_is_warmed_and_pointed_at_its_own_seed(self):
        for keep in (("gradle",), ("maven",), ("gradle", "maven")):
            with self.subTest(prime=keep):
                args = self.built(*keep).build_args
                self.assertEqual([args[f"WITH_{tool.upper()}_PRIME"] for tool in ("gradle", "maven")],
                                 ["yes" if tool in keep else "no" for tool in ("gradle", "maven")])
                self.assertEqual(args["PRIME_GRADLE_HOME"],
                                 f"{plan.PRIME_ROOT}/gradle-home" if "gradle" in keep
                                 else f"{plan.RUNNER_HOME}/.gradle")
                self.assertEqual(args["PRIME_MAVEN_ARGS"],
                                 f"-Dmaven.repo.local={plan.PRIME_ROOT}/maven-repo" if "maven" in keep else "")
                self.assertEqual(args["OPT_EXPECTED"].split()[-1], "prime")

    def test_the_seeds_are_exactly_the_warmers_the_contract_defines(self):
        self.assertEqual(sorted(plan.PRIME_SEEDS), sorted(prime_contract.TOOLS))
        for tool, seed in plan.PRIME_SEEDS.items():
            with self.subTest(tool=tool):
                self.assertIn(f"warm-{tool}.sh warm /tmp/prime/{tool} {plan.PRIME_ROOT}/{seed}", DOCKERFILE)
                self.assertIn(f"warm-{tool}.sh prove /tmp/prime/{tool} {plan.PRIME_ROOT}/{seed}", DOCKERFILE)

    def test_the_tag_moves_with_the_prime_and_the_warmers_and_an_unprimed_tag_moves_with_neither(self):
        bare, gradle_only, both = self.built(), self.built("gradle"), self.built("gradle", "maven")
        self.assertEqual(len({bare.tag, gradle_only.tag, both.tag}), 3, "a tag names the prime it was warmed for")
        prime = self.projects("maven")
        with tempfile.TemporaryDirectory() as scratch:
            # ⭐ The context is copied by the ONE helper, reading the
            # declaration a primed build's digest is taken over — never a list
            # of directories written out here.
            root = build_inputs.copy_inputs(scratch, inputs=build.PRIMED_INPUT_ROOTS)
            before = (build.planned(root, AMD64, ["java", "maven"]).tag,
                      build.planned(root, AMD64, ["java", "maven"], prime).tag)
            with (root / build.WARMERS / "warm-maven.sh").open("a", encoding="utf-8") as handle:
                handle.write("\n")
            self.assertEqual(build.planned(root, AMD64, ["java", "maven"]).tag, before[0])
            self.assertNotEqual(build.planned(root, AMD64, ["java", "maven"], prime).tag, before[1])
        shutil.rmtree(prime.parent, ignore_errors=True)

    def test_a_prime_the_declared_set_cannot_build_is_refused_before_docker_starts(self):
        prime = self.projects("maven")
        command = [sys.executable, str(ROOT / "docker" / "minimal" / "build.py"), "--platform", AMD64,
                   "--print-tag", "--prime", str(prime)]
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        refused = subprocess.run(command + ["--runtimes", "java"], env=env, capture_output=True, text=True,
                                 stdin=subprocess.DEVNULL)
        self.assertEqual(refused.returncode, 2, refused.stdout)
        self.assertIn("the declared set does not hold", refused.stderr)
        self.assertNotIn("Traceback", refused.stderr)
        accepted = subprocess.run(command + ["--runtimes", "java,maven"], env=env, capture_output=True, text=True,
                                  stdin=subprocess.DEVNULL)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        shutil.rmtree(prime.parent, ignore_errors=True)

    def test_every_build_names_the_prime_context_and_the_empty_one_is_empty(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            self.assertIn(f"consumer-prime={build.empty_context(root)}", build.docker_command(root, self.built()))
            self.assertEqual(list(build.empty_context(root).iterdir()), [])
        prime = self.projects("maven")
        self.assertIn(f"consumer-prime={prime}", build.docker_command(ROOT, self.built("maven"), prime=prime))
        shutil.rmtree(prime.parent, ignore_errors=True)

    def test_the_seed_is_proved_offline_and_the_tools_are_pointed_at_it_after_the_checks(self):
        runner = DOCKERFILE[DOCKERFILE.index("FROM ${RUNNER_BASE} AS runner"):]
        warm = runner.index("--mount=type=bind,from=consumer-prime")
        prove = runner.index("RUN --network=none --mount=type=bind,from=consumer-prime")
        checks = runner.index('held="$(ls -A /opt | xargs)"')
        self.assertLess(warm, prove, "the seed is warmed before it is proved")
        self.assertLess(prove, checks, "/opt is checked once the seed is there")
        for line in ("ENV GRADLE_USER_HOME=${PRIME_GRADLE_HOME}", "ENV MAVEN_ARGS=${PRIME_MAVEN_ARGS}"):
            with self.subTest(line=line):
                self.assertLess(checks, runner.index(line), "a version check must not write into a reader's seed")


class TheRunLine(unittest.TestCase):
    def test_the_documented_run_line_mounts_no_socket_and_opens_nothing(self):
        self.assertEqual(plan.run_line_findings(README), [])

    def test_each_planted_run_line_defect_is_found(self):
        good = "docker run -d --init --network none -v src:/work tag"
        self.assertEqual(plan.run_line_findings(good), [])
        for planted in (
            good + " -v /var/run/docker.sock:/var/run/docker.sock",
            good.replace("--network none", ""),
            good + " -p 8080:8080",
        ):
            with self.subTest(planted=planted):
                self.assertNotEqual(plan.run_line_findings(planted), [])


class TheWarmCheck(unittest.TestCase):
    def test_exact_agreement_passes_and_every_difference_is_named(self):
        expected = {"a.jar": "1" * 64, "a.pom": "2" * 64}
        self.assertEqual(verify_repo.compare(expected, dict(expected)), [])
        self.assertEqual(verify_repo.compare(expected, {**expected, "b.jar": "3" * 64}), ["unpinned file: b.jar"])
        self.assertEqual(verify_repo.compare(expected, {"a.jar": "1" * 64}), ["missing file: a.pom"])
        self.assertEqual(
            verify_repo.compare(expected, {"a.jar": "1" * 64, "a.pom": "9" * 64}),
            ["checksum differs from pins.json: a.pom"],
        )


class TheSmokeProjects(unittest.TestCase):
    def test_there_is_one_per_runtime_and_each_plant_applies_once(self):
        found = sorted(p.parent.name for p in SMOKE.glob("*/smoke.json"))
        self.assertEqual(found, sorted(PINS["runtimes"]))
        for path in SMOKE.glob("*/smoke.json"):
            with self.subTest(smoke=path.parent.name):
                smoke = json.loads(path.read_text(encoding="utf-8"))
                plan.plan(PINS, smoke["runtimes"], AMD64, DIGEST)
                source = (path.parent / smoke["plant"]["file"]).read_text(encoding="utf-8")
                self.assertEqual(source.count(smoke["plant"]["from"]), 1)


if __name__ == "__main__":
    unittest.main()
