"""The prime contract — its reading, its guards, its plan and its warmers, with no Docker.

Run from the component root: `python3 -m unittest discover -s tests -v`.
Every rule is asserted BOTH ways: the fixture prime passes, and a planted
violation is refused naming why. The warmers are shell scripts; their source
check runs here on real-shaped logs, and their commands run against a fake
`gradle` and `mvn` that only record what they were given.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDITOR = ROOT / "docker" / "editor"
PRIME = ROOT / "prime"
FIXTURE = ROOT / "tests" / "fixtures" / "prime"
sys.path.insert(0, str(EDITOR))

import editor_plan  # noqa: E402

prime = editor_plan.prime_contract
runner_plan = editor_plan.runner_plan
_spec = importlib.util.spec_from_file_location("editor_build_for_prime", EDITOR / "build.py")
editor_build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(editor_build)

PINS = runner_plan.load(ROOT)
EPINS = editor_plan.load(ROOT)
SET = ("gradle", "java", "maven")
JDK = int(PINS["runtimes"]["java"]["version"].split(".")[0].split("+")[0])
KOTLIN = PINS["runtimes"]["kotlin"]["version"]
GRADLE = PINS["runtimes"]["gradle"]["version"]
GRADLE_SHA = PINS["runtimes"]["gradle"]["archives"]["any"]["sha256"]
MAVEN = PINS["runtimes"]["maven"]["version"]
DOCKERFILE = (ROOT / editor_plan.DOCKERFILE).read_text(encoding="utf-8")
ENTRYPOINT = (EDITOR / "entrypoint.sh").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def planted(tmp: str, edit=None) -> Path:
    """A copy of the fixture prime with one defect planted by `edit(root)`."""
    root = Path(tmp) / "prime"
    shutil.copytree(FIXTURE, root)
    if edit:
        edit(root)
    return root


def replace(root: Path, relative: str, old: str, new: str) -> None:
    path = root / relative
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    path.write_text(text.replace(old, new), encoding="utf-8")


def write(root: Path, relative: str, text: str) -> None:
    (root / relative).parent.mkdir(parents=True, exist_ok=True)
    (root / relative).write_text(text, encoding="utf-8")


def plan_for(prime_read=None, names=SET) -> editor_plan.EditorPlan:
    runner = runner_plan.plan(PINS, list(names), "linux/amd64", "0" * 64)
    return editor_plan.plan(PINS, EPINS, runner, "0" * 64, prime_read)


class TheReading(unittest.TestCase):
    def test_the_fixture_is_read_with_every_version_its_build_files_name(self):
        read = prime.read(FIXTURE)
        self.assertEqual(read.tools, ("gradle", "maven"))
        self.assertEqual(read.kotlin_plugins, (("gradle/kotlin/build.gradle.kts", KOTLIN),))
        self.assertEqual(sorted(read.toolchains), [("gradle/java/build.gradle.kts", JDK),
                                                   ("gradle/kotlin/build.gradle.kts", JDK)])
        self.assertEqual(read.maven_releases, (("maven/parent/pom.xml", JDK),))
        self.assertIsNone(read.gradle_wrapper)
        self.assertIsNone(read.maven_wrapper)

    def test_each_shape_the_warmers_cannot_use_is_refused_naming_why(self):
        cases = {
            "a stray directory": (lambda r: (r / "npm").mkdir(), "['npm']"),
            "no project": (lambda r: [shutil.rmtree(r / t) for t in ("gradle", "maven")], "primes nothing"),
            "no settings": (lambda r: (r / "gradle" / "settings.gradle.kts").unlink(), "not a Gradle build"),
            "no verification": (lambda r: (r / "gradle" / prime.GRADLE_VERIFICATION).unlink(),
                                "pinned by nothing"),
            "verification off": (lambda r: replace(r, f"gradle/{prime.GRADLE_VERIFICATION}",
                                                   "<verify-metadata>true", "<verify-metadata>false"),
                                 "verify-metadata"),
            "an artifact with no sha256": (lambda r: replace(r, f"gradle/{prime.GRADLE_VERIFICATION}",
                                                             '<sha256 value="57928d6e', '<sha1 value="57928d6e'),
                                           "gson-2.11.0.jar"),
            "no pom": (lambda r: (r / "maven" / "pom.xml").unlink(), "not a Maven build"),
            "a malformed pom": (lambda r: write(r, "maven/parent/pom.xml", "<project>"), "not well-formed"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(prime.read(planted(tmp)).tools, ("gradle", "maven"))
        for label, (edit, needle) in cases.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(prime.Refused) as caught:
                    prime.read(planted(tmp, edit))
                self.assertIn(needle, str(caught.exception))

    def test_a_prime_with_one_project_is_read_as_that_project_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            read = prime.read(planted(tmp, lambda r: shutil.rmtree(r / "gradle")))
        self.assertEqual(read.tools, ("maven",))

    def test_the_digest_moves_with_any_byte_and_not_with_where_the_prime_sits(self):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            self.assertEqual(prime.digest(planted(one)), prime.digest(FIXTURE))
            changed = planted(two, lambda r: replace(r, "maven/src/main/java/prime/Adder.java", "a + b", "b + a"))
            self.assertNotEqual(prime.digest(changed), prime.digest(FIXTURE))


class TheGuard(unittest.TestCase):
    def refused(self, edit, names=SET) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            read = prime.read(planted(tmp, edit))
        with self.assertRaises(prime.Refused) as caught:
            prime.guard(read, PINS, names)
        return str(caught.exception)

    def test_the_fixture_agrees_with_the_pins(self):
        prime.guard(prime.read(FIXTURE), PINS, SET)

    def test_a_project_whose_tool_is_not_declared_is_refused_naming_it(self):
        message = self.refused(None, ("java", "maven"))
        self.assertIn("['gradle']", message)
        with tempfile.TemporaryDirectory() as tmp:
            prime.guard(prime.read(planted(tmp, lambda r: shutil.rmtree(r / "gradle"))), PINS, ("java", "maven"))

    def test_another_kotlin_plugin_is_refused_naming_the_file_and_both_versions(self):
        message = self.refused(lambda r: replace(r, "gradle/kotlin/build.gradle.kts", f'"{KOTLIN}"', '"2.3.0"'))
        for needle in ("gradle/kotlin/build.gradle.kts", "2.3.0", KOTLIN, "misses"):
            self.assertIn(needle, message)

    def test_a_plugin_id_form_and_a_version_catalog_are_guarded_too(self):
        by_id = self.refused(lambda r: write(r, "gradle/other.gradle.kts",
                                             'plugins { id("org.jetbrains.kotlin.jvm") version "2.2.0" }\n'))
        self.assertIn("gradle/other.gradle.kts names the Kotlin plugin 2.2.0", by_id)
        toml = self.refused(lambda r: write(r, "gradle/gradle/libs.versions.toml", '[versions]\nkotlin = "2.1.0"\n'))
        self.assertIn("gradle/gradle/libs.versions.toml names the Kotlin plugin 2.1.0", toml)

    def test_another_java_toolchain_is_refused_because_offline_cannot_provision_it(self):
        message = self.refused(lambda r: replace(r, "gradle/java/build.gradle.kts", f"of({JDK})", f"of({JDK + 1})"))
        self.assertIn(f"a Java {JDK + 1} toolchain, and the image's JDK is {JDK}", message)
        self.assertIn("cannot provision", message)
        kotlin = self.refused(lambda r: replace(r, "gradle/kotlin/build.gradle.kts", f"({JDK})", "(21)"))
        self.assertIn("gradle/kotlin/build.gradle.kts asks for a Java 21 toolchain", kotlin)

    def test_a_maven_release_newer_than_the_jdk_is_refused_and_an_older_one_is_not(self):
        release = "<maven.compiler.release>"
        message = self.refused(lambda r: replace(r, "maven/parent/pom.xml", f"{release}{JDK}", f"{release}{JDK + 1}"))
        self.assertIn(f"maven/parent/pom.xml compiles for Java {JDK + 1}", message)
        with tempfile.TemporaryDirectory() as tmp:
            older = planted(tmp, lambda r: replace(r, "maven/parent/pom.xml", f"{release}{JDK}", f"{release}17"))
            prime.guard(prime.read(older), PINS, SET)

    def test_a_compiler_plugin_release_reached_through_a_property_is_guarded(self):
        plugin = ("<build><plugins><plugin><artifactId>maven-compiler-plugin</artifactId>"
                  "<configuration><release>${java.level}</release></configuration></plugin></plugins></build>"
                  f"<properties><java.level>{JDK + 2}</java.level></properties>\n</project>")
        message = self.refused(lambda r: replace(r, "maven/pom.xml", "</project>", plugin))
        self.assertIn(f"maven/pom.xml compiles for Java {JDK + 2}", message)

    def test_a_gradle_wrapper_must_name_the_pinned_gradle_and_pin_its_sha256(self):
        good = (f"distributionUrl=https\\://services.gradle.org/distributions/gradle-{GRADLE}-bin.zip\n"
                f"distributionSha256Sum={GRADLE_SHA}\n")
        wrapper = f"gradle/{prime.GRADLE_WRAPPER}"
        with tempfile.TemporaryDirectory() as tmp:
            read = prime.read(planted(tmp, lambda r: write(r, wrapper, good)))
            self.assertEqual(read.gradle_wrapper, (wrapper, GRADLE, GRADLE_SHA))
            prime.guard(read, PINS, SET)
        other = self.refused(lambda r: write(r, wrapper, good.replace(f"gradle-{GRADLE}-", "gradle-9.0.0-")))
        self.assertIn(f"{wrapper} names Gradle 9.0.0, and the image's Gradle is {GRADLE}", other)
        unpinned = self.refused(lambda r: write(r, wrapper, good.splitlines()[0] + "\n"))
        self.assertIn("does not pin distributionSha256Sum", unpinned)

    def test_a_maven_wrapper_must_name_the_pinned_maven(self):
        url = "distributionUrl=https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/{0}/apache-maven-{0}-bin.zip\n"
        wrapper = f"maven/{prime.MAVEN_WRAPPER}"
        with tempfile.TemporaryDirectory() as tmp:
            prime.guard(prime.read(planted(tmp, lambda r: write(r, wrapper, url.format(MAVEN)))), PINS, SET)
        message = self.refused(lambda r: write(r, wrapper, url.format("3.8.8")))
        self.assertIn(f"{wrapper} names Maven 3.8.8, and the image's Maven is {MAVEN}", message)


class ThePlan(unittest.TestCase):
    def test_without_a_prime_nothing_is_warmed_and_with_one_each_declared_project_is(self):
        self.assertEqual({k: v for k, v in plan_for().build_args.items() if "PRIME" in k},
                         {"WITH_GRADLE_PRIME": "no", "WITH_MAVEN_PRIME": "no", "PRIME_KEY": "none"})
        read = prime.read(FIXTURE)
        self.assertEqual({k: v for k, v in plan_for(read).build_args.items() if "PRIME" in k},
                         {"WITH_GRADLE_PRIME": "yes", "WITH_MAVEN_PRIME": "yes", "PRIME_KEY": read.digest})

    def test_the_prime_moves_the_tag_and_only_its_digest_does(self):
        bare, warmed = plan_for().tag, plan_for(prime.read(FIXTURE)).tag
        self.assertNotEqual(bare, warmed)
        self.assertEqual(bare.rsplit("-", 1)[0], warmed.rsplit("-", 1)[0])
        with tempfile.TemporaryDirectory() as tmp:
            other = planted(tmp, lambda r: replace(r, "maven/src/main/java/prime/Adder.java", "a + b", "b + a"))
            self.assertNotEqual(plan_for(prime.read(other)).tag, warmed)

    def test_the_plan_runs_the_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            read = prime.read(planted(tmp, lambda r: replace(r, "gradle/kotlin/build.gradle.kts",
                                                             f'"{KOTLIN}"', '"2.3.0"')))
        with self.assertRaises(prime.Refused):
            plan_for(read)

    def test_the_cli_refuses_before_docker_starts_naming_why_and_prints_a_tag_for_a_good_prime(self):
        env = {"PATH": "/nonexistent", "PYTHONDONTWRITEBYTECODE": "1"}
        command = [sys.executable, str(EDITOR / "build.py"), "--runtimes", ",".join(SET), "--print-tag"]
        cases = {
            "a version mismatch": (lambda r: replace(r, "gradle/java/build.gradle.kts", f"of({JDK})", "of(8)"),
                                   "a Java 8 toolchain"),
            "no project": (lambda r: [shutil.rmtree(r / t) for t in ("gradle", "maven")], "primes nothing"),
        }
        for label, (edit, needle) in cases.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                refused = subprocess.run(command + ["--prime", str(planted(tmp, edit))], env=env,
                                         capture_output=True, text=True, stdin=subprocess.DEVNULL)
                self.assertEqual(refused.returncode, 2, refused.stderr)
                self.assertIn(needle, refused.stderr)
        good = subprocess.run(command + ["--prime", str(FIXTURE)], env=env, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)
        self.assertEqual(good.returncode, 0, good.stderr)
        platform = editor_build.runner_build.host_platform()
        self.assertEqual(good.stdout.strip(), editor_build.planned(ROOT, platform, SET, FIXTURE).tag)

    def test_the_prime_is_the_named_context_and_the_runner_is_built_by_its_own_command(self):
        built = editor_build.planned(ROOT, "linux/amd64", SET, FIXTURE)
        command = editor_build.docker_command(ROOT, built, FIXTURE)
        self.assertIn(f"consumer-prime={FIXTURE}", command[command.index("--build-context") + 1])
        runner = editor_build.runner_command(ROOT, "linux/amd64", SET)
        self.assertNotIn("--no-cache-filter", runner, "the runner's warm cache is keyed now")
        own = runner_plan.plan(PINS, list(SET), "linux/amd64", runner_plan.inputs_digest(ROOT))
        self.assertEqual(runner, editor_build.runner_build.docker_command(ROOT, own))


def run_sh(*args, env=None, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(["sh", *map(str, args)], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                          env=env, cwd=cwd)


GRADLE_LOG = """> Task :java:compileJava{0}
> Task :java:processResources NO-SOURCE
> Task :java:compileTestJava{0}
> Task :java:test{0}
> Task :kotlin:compileKotlin
> Task :kotlin:compileJava NO-SOURCE
> Task :kotlin:compileTestKotlin
> Task :kotlin:compileTestJava NO-SOURCE
> Task :kotlin:test
BUILD SUCCESSFUL in 1s
"""
MAVEN_LOG = """[INFO] --- compiler:3.15.0:compile (default-compile) @ prime ---
[INFO] {0}
[INFO] --- compiler:3.15.0:testCompile (default-testCompile) @ prime ---
[INFO] Compiling 1 source file with javac [debug release 25] to target/test-classes
[INFO] --- surefire:3.5.4:test (default-test) @ prime ---
[INFO] {1}
[INFO] BUILD SUCCESS
"""


class TheWarmersSourceCheck(unittest.TestCase):
    def check(self, script: str, log: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "build.log"
            path.write_text(log, encoding="utf-8")
            return run_sh(PRIME / script, "check", path)

    def test_gradle_passes_real_sources_and_a_pure_kotlin_projects_empty_compile_java(self):
        self.assertEqual(self.check("warm-gradle.sh", GRADLE_LOG.format("")).returncode, 0)
        self.assertEqual(self.check("warm-gradle.sh", GRADLE_LOG.format(" FROM-CACHE")).returncode, 0)

    def test_gradle_fails_a_project_with_no_sources_naming_it_and_why(self):
        failed = self.check("warm-gradle.sh", GRADLE_LOG.format(" NO-SOURCE"))
        self.assertEqual(failed.returncode, 1)
        for kind in ("main compile task", "test compile task", "test task"):
            self.assertIn(f"gradle project :java ran no {kind}", failed.stderr)
        self.assertIn("never resolves its classpath", failed.stderr)
        self.assertNotIn(":kotlin", failed.stderr)
        nothing = self.check("warm-gradle.sh", "> Task :build UP-TO-DATE\nBUILD SUCCESSFUL\n")
        self.assertEqual(nothing.returncode, 1)
        self.assertIn("compiled nothing", nothing.stderr)

    def test_maven_passes_real_sources_and_fails_no_sources_or_no_tests_naming_the_module(self):
        good = MAVEN_LOG.format("Compiling 1 source file", "Tests run: 1, Failures: 0, Errors: 0, Skipped: 0")
        self.assertEqual(self.check("warm-maven.sh", good).returncode, 0)
        for main, tests, needle in (
                ("No sources to compile", "Tests run: 1, Failures: 0", "module prime compiles no sources in compile"),
                ("Compiling 1 source file", "No tests to run.", "module prime runs no tests"),
                ("Compiling 1 source file", "Tests are skipped.", "module prime runs no tests"),
                ("Compiling 1 source file", "Tests run: 0, Failures: 0", "ran no test")):
            with self.subTest(needle):
                failed = self.check("warm-maven.sh", MAVEN_LOG.format(main, tests))
                self.assertEqual(failed.returncode, 1)
                self.assertIn(needle, failed.stderr)


FAKE = """#!/bin/sh
printf '%s\\n' "$0" "$@" > "$RECORD"
printf 'HOME=%s\\n' "${GRADLE_USER_HOME:-}" >> "$RECORD"
cat "$LOG"
"""


class TheWarmersCommands(unittest.TestCase):
    """The warm and the proof, against fakes that record their arguments and print a passing log."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="prime-warm-"))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for tool in ("gradle", "mvn"):
            (self.bin / tool).write_text(FAKE, encoding="utf-8")
            (self.bin / tool).chmod(0o755)
        self.record = self.tmp / "record"
        self.env = {"PATH": f"{self.bin}:{os.environ['PATH']}", "RECORD": str(self.record)}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def warm(self, script: str, mode: str, project: Path, seed: Path, log: str) -> subprocess.CompletedProcess:
        (self.tmp / "log").write_text(log, encoding="utf-8")
        return run_sh(PRIME / script, mode, project, seed, env={**self.env, "LOG": str(self.tmp / "log")})

    def test_maven_warms_with_strict_checksums_a_placeholder_agent_and_no_bookkeeping(self):
        seed = self.tmp / "repo"
        (seed / "g" / "a").mkdir(parents=True)
        for name in ("_remote.repositories", "a.jar.lastUpdated", "resolver-status.properties", "a.jar"):
            (seed / "g" / "a" / name).write_text("x", encoding="utf-8")
        log = MAVEN_LOG.format("Compiling 1 source file", "Tests run: 1, Failures: 0")
        warmed = self.warm("warm-maven.sh", "warm", FIXTURE / "maven", seed, log)
        self.assertEqual(warmed.returncode, 0, warmed.stderr)
        args = self.record.read_text(encoding="utf-8").splitlines()
        for needed in ("-C", f"-Dmaven.repo.local={seed}", "-Daether.connector.userAgent=Example/0.1 "
                       "(+https://example.invalid)", "test"):
            self.assertIn(needed, args)
        self.assertNotIn("-o", args)
        self.assertEqual(sorted(p.name for p in (seed / "g" / "a").iterdir()), ["a.jar"])

    def test_maven_proves_offline_on_a_copy_and_leaves_the_repository_alone(self):
        seed = self.tmp / "repo"
        seed.mkdir()
        (seed / "kept").write_text("x", encoding="utf-8")
        log = MAVEN_LOG.format("Compiling 1 source file", "Tests run: 1, Failures: 0")
        proved = self.warm("warm-maven.sh", "prove", FIXTURE / "maven", seed, log)
        self.assertEqual(proved.returncode, 0, proved.stderr)
        args = self.record.read_text(encoding="utf-8").splitlines()
        self.assertIn("-o", args)
        self.assertNotIn(f"-Dmaven.repo.local={seed}", args)
        self.assertEqual([p.name for p in seed.iterdir()], ["kept"])
        failed = self.warm("warm-maven.sh", "prove", FIXTURE / "maven", seed, MAVEN_LOG.format(
            "No sources to compile", "Tests run: 1"))
        self.assertEqual(failed.returncode, 1)

    def test_gradle_warms_into_the_seed_and_drops_what_belongs_to_that_build(self):
        seed = self.tmp / "home"
        for name in ("daemon/9/registry.bin", "caches/modules-2/x.lock", "caches/modules-2/files-2.1/kept.jar"):
            (seed / name).parent.mkdir(parents=True, exist_ok=True)
            (seed / name).write_text("x", encoding="utf-8")
        warmed = self.warm("warm-gradle.sh", "warm", FIXTURE / "gradle", seed, GRADLE_LOG.format(""))
        self.assertEqual(warmed.returncode, 0, warmed.stderr)
        record = self.record.read_text(encoding="utf-8").splitlines()
        self.assertTrue(record[0].endswith("/gradle"), "no wrapper in the prime: the pinned gradle runs")
        self.assertIn("build", record)
        self.assertIn(f"HOME={seed}", record)
        self.assertNotIn("--offline", record)
        self.assertEqual([str(p.relative_to(seed)) for p in sorted(seed.rglob("*")) if p.is_file()],
                         ["caches/modules-2/files-2.1/kept.jar"])
        self.assertTrue(os.stat(seed / "caches").st_mode & stat.S_IROTH)

    def test_gradle_proves_offline_on_a_copy_and_uses_a_wrapper_when_the_prime_carries_one(self):
        seed = self.tmp / "home"
        seed.mkdir()
        project = self.tmp / "project"
        shutil.copytree(FIXTURE / "gradle", project)
        (project / "gradlew").write_text(FAKE, encoding="utf-8")
        proved = self.warm("warm-gradle.sh", "prove", project, seed, GRADLE_LOG.format(""))
        self.assertEqual(proved.returncode, 0, proved.stderr)
        record = self.record.read_text(encoding="utf-8").splitlines()
        self.assertTrue(record[0].endswith("gradlew"), record[0])
        self.assertIn("--offline", record)
        self.assertNotIn(f"HOME={seed}", record)
        self.assertEqual(list(seed.iterdir()), [])
        failed = self.warm("warm-gradle.sh", "prove", project, seed, GRADLE_LOG.format(" NO-SOURCE"))
        self.assertEqual(failed.returncode, 1)
        self.assertIn(":java", failed.stderr)


def code(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


class TheImageShape(unittest.TestCase):
    def test_the_warm_reads_the_named_context_then_proves_offline_before_the_check_step(self):
        body = code(DOCKERFILE)
        warm = body.index("warm-gradle.sh warm")
        prove = body.index("warm-gradle.sh prove")
        self.assertLess(warm, prove)
        self.assertLess(prove, body.index("toolchain-versions"), "the check step still runs last")
        self.assertEqual(body.count("--mount=type=bind,from=consumer-prime,target=/tmp/prime"), 2)
        proof_run = body[body.rindex("RUN", 0, prove):prove]
        self.assertIn("RUN --network=none", proof_run)
        warm_run = body[body.rindex("RUN", 0, warm):warm]
        self.assertIn("${PRIME_KEY}", warm_run)

    def test_the_entrypoint_seeds_each_cache_only_into_an_empty_directory(self):
        self.assertIn('seed_tree "$SEED_GRADLE" "${GRADLE_USER_HOME:-${HOME:-/home/coder}/.gradle}"', ENTRYPOINT)
        self.assertIn('seed_tree "$SEED_MAVEN" "${HOME:-/home/coder}/.m2/repository"', ENTRYPOINT)
        self.assertIn("is not empty; leaving it alone", ENTRYPOINT)
        self.assertRegex(DOCKERFILE, r"install -d -o 1000 -g 1000 [^\n]*/home/coder/\.m2")

    def test_the_readme_states_the_contract_and_what_the_image_guarantees(self):
        section = README.split("### The prime", 1)[1].split("\n## ", 1)[0]
        for needle in ("--prime", "consumer-prime", "verification-metadata.xml", "relativePath",
                       "The sources must be real", "refused before\n  Docker starts", "gradle build\n--offline",
                       "mvn -o test", "/opt/code-server/prime/gradle-home", "~/.m2/repository"):
            self.assertIn(needle, section)
        self.assertNotIn("docker run", section)

    def test_nothing_names_the_extraction_source_or_a_path_outside_the_component(self):
        for path in sorted(list(PRIME.rglob("*")) + list(FIXTURE.rglob("*"))):
            if path.is_file() and "__pycache__" not in path.parts:
                with self.subTest(file=path.name):
                    text = path.read_text(encoding="utf-8").lower()
                    self.assertNotIn("codesignal", text)
                    self.assertNotIn("../", text)
                    self.assertNotIn("/home/", text.replace("/home/coder", ""))


if __name__ == "__main__":
    unittest.main()
