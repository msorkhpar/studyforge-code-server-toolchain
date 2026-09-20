"""A corpus's practice caches in the RUNNER (W390), built and run for real — both ways.

⛔ Skipped unless `TC_DOCKER=1`: it builds images and starts containers. Run it
as ONE container job (the whole module under whatever lock the host uses):

    TC_DOCKER=1 python3 -m unittest tests.test_runner_prime_image -v

It builds the `gradle,java,maven` runner warmed from the FIXTURE prime
(`tests/fixtures/prime/`, placeholders, no consumer's project) and the same set
with no prime. ⭐ THE READING THIS MODULE EXISTS FOR: every container runs
`--network none` and as an ARBITRARY uid, because that is how the documented
run line starts one — and a graded run passes NO cache flag of its own, so it
is the image that must carry the dependencies. Images are removed afterwards
unless `TC_KEEP_IMAGES=1`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docker" / "minimal"))

import build as runner_build  # noqa: E402
import plan  # noqa: E402

BUILD = ROOT / "docker" / "minimal" / "build.py"
FIXTURE = ROOT / "tests" / "fixtures" / "prime"
SET = ("gradle", "java", "maven")
#: An arbitrary uid with no passwd entry: the documented run line passes the
#: READER's own, which is never root and never known to the image.
READER = "4242:4242"
WORK = "/work"


def run(command: list, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in command], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          **kwargs)


def build_image(prime: Path | None) -> subprocess.CompletedProcess:
    return run([sys.executable, BUILD, "--runtimes", ",".join(SET)] + (["--prime", prime] if prime else []))


def tag(prime: Path | None) -> str:
    return runner_build.planned(ROOT, runner_build.host_platform(), list(SET), prime).tag


@unittest.skipUnless(os.environ.get("TC_DOCKER") == "1", "set TC_DOCKER=1 to build and run the images")
class TheWarmedRunner(unittest.TestCase):
    containers: list[str] = []

    @classmethod
    def setUpClass(cls):
        for label, prime in (("primed", FIXTURE), ("bare", None)):
            built = build_image(prime)
            if built.returncode != 0:
                raise AssertionError(f"the {label} runner did not build:\n{built.stdout[-4000:]}{built.stderr[-2000:]}")
        cls.image, cls.bare = tag(FIXTURE), tag(None)
        cls.primed_runner, cls.bare_runner = cls.start(cls.image), cls.start(cls.bare)

    @classmethod
    def tearDownClass(cls):
        for name in cls.containers:
            run(["docker", "rm", "-f", name])
        if os.environ.get("TC_KEEP_IMAGES") != "1":
            for image in (cls.image, cls.bare):
                run(["docker", "image", "rm", "-f", image])
        shutil.rmtree(ROOT / ".work" / "no-prime", ignore_errors=True)

    # ------------------------------------------------------------ helpers
    @classmethod
    def start(cls, image: str) -> str:
        """A container as the documented run line starts one, holding the fixture at /work."""
        name = f"w390-runner-{uuid.uuid4().hex[:8]}"
        cls.containers.append(name)
        started = run(["docker", "run", "-d", "--name", name, "--init", "--network", "none", "--user", READER, image])
        assert started.returncode == 0, started.stderr
        copied = run(["docker", "cp", f"{FIXTURE}/.", f"{name}:{WORK}"])
        assert copied.returncode == 0, copied.stderr
        owned = run(["docker", "exec", "-u", "0", name, "chown", "-R", READER, WORK])
        assert owned.returncode == 0, owned.stderr
        return name

    @staticmethod
    def exec(container: str, script: str) -> subprocess.CompletedProcess:
        """What the runner does from outside: `docker exec`, no login shell, no extra environment."""
        return run(["docker", "exec", container, "sh", "-c", script])

    def graded(self, container: str, tool: str) -> subprocess.CompletedProcess:
        """A graded run as `TC-01/6` makes one: offline, and with no cache flag of its own."""
        commands = {"gradle": f"cd {WORK}/gradle && gradle build --offline --no-daemon --console=plain",
                    "maven": f"cd {WORK}/maven && mvn -B -o test"}
        for flag in ("-Dmaven.repo.local", "GRADLE_USER_HOME", plan.PRIME_ROOT):
            self.assertNotIn(flag, commands[tool], "the image carries the caches; the run line says nothing")
        return self.exec(container, commands[tool])

    # ---------------------------------------------------------- acceptance
    def test_a_graded_gradle_run_resolves_offline_and_every_compile_and_test_task_runs(self):
        built = self.graded(self.primed_runner, "gradle")
        self.assertEqual(built.returncode, 0, built.stdout[-3000:] + built.stderr[-2000:])
        self.assertIn("BUILD SUCCESSFUL", built.stdout)
        for task in (":java:compileJava", ":java:test", ":kotlin:compileKotlin", ":kotlin:test"):
            self.assertRegex(built.stdout, rf"(?m)^> Task {task}$")

    def test_a_graded_maven_run_resolves_offline_what_the_pom_declares(self):
        tested = self.graded(self.primed_runner, "maven")
        self.assertEqual(tested.returncode, 0, tested.stdout[-3000:] + tested.stderr[-2000:])
        self.assertIn("Tests run: 1, Failures: 0, Errors: 0, Skipped: 0", tested.stdout)
        declared = self.exec(self.primed_runner, f"ls {plan.PRIME_ROOT}/maven-repo/org/assertj/assertj-core")
        self.assertEqual(declared.stdout.split(), ["3.26.3"])

    def test_without_the_seed_the_same_runs_fail_offline(self):
        """The other way: it is the seed, not something else in the image, that made them work."""
        gradle = self.exec(self.primed_runner, f"cp -r {WORK}/gradle /tmp/g && cd /tmp/g && "
                                               "GRADLE_USER_HOME=/tmp/empty-home gradle build --offline "
                                               "--no-daemon --console=plain")
        self.assertNotEqual(gradle.returncode, 0)
        maven = self.exec(self.primed_runner, f"cp -r {WORK}/maven /tmp/m && cd /tmp/m && "
                                              "mvn -B -o -Dmaven.repo.local=/tmp/empty test")
        self.assertNotEqual(maven.returncode, 0)

    def test_a_runner_built_with_no_prime_holds_no_seed_and_the_same_runs_fail(self):
        self.assertNotEqual(self.bare, self.image, "the prime's digest is part of the tag")
        held = self.exec(self.bare_runner, f"ls -d {plan.PRIME_ROOT}")
        self.assertNotEqual(held.returncode, 0, held.stdout)
        environment = self.exec(self.bare_runner, 'printf "%s|%s" "$MAVEN_ARGS" "$GRADLE_USER_HOME"')
        self.assertEqual(environment.stdout, f"|{plan.RUNNER_HOME}/.gradle")
        for tool in ("gradle", "maven"):
            with self.subTest(tool=tool):
                self.assertNotEqual(self.graded(self.bare_runner, tool).returncode, 0)

    def test_the_seed_is_writable_by_the_reader_and_holds_what_each_tool_looks_for(self):
        """⛔ The run line passes the reader's own uid, and both tools write into their cache."""
        environment = self.exec(self.primed_runner, 'printf "%s|%s" "$MAVEN_ARGS" "$GRADLE_USER_HOME"')
        self.assertEqual(environment.stdout,
                         f"-Dmaven.repo.local={plan.PRIME_ROOT}/maven-repo|{plan.PRIME_ROOT}/gradle-home")
        for seed in plan.PRIME_SEEDS.values():
            with self.subTest(seed=seed):
                written = self.exec(self.primed_runner, f"test -w {plan.PRIME_ROOT}/{seed} && "
                                                        f"touch {plan.PRIME_ROOT}/{seed}/.reader-can-write")
                self.assertEqual(written.returncode, 0, written.stderr)

    def test_opt_holds_the_declared_set_and_the_seed_and_the_bare_image_holds_no_seed(self):
        for container, primed in ((self.primed_runner, True), (self.bare_runner, False)):
            with self.subTest(primed=primed):
                held = self.exec(container, "LC_ALL=C ls -A /opt | xargs")
                expected = plan.opt_dirs(SET) + (["prime"] if primed else [])
                self.assertEqual(held.stdout.split(), expected)


if __name__ == "__main__":
    unittest.main()
