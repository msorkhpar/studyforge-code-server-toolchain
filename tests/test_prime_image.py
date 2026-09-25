"""The prime, built and run for real — both ways.

⛔ Skipped unless `TC_DOCKER=1`: it builds images and starts containers. Run it
as ONE container job (the whole module under whatever lock the host uses):

    TC_DOCKER=1 python3 -m unittest tests.test_prime_image -v

It builds the `gradle,java,maven` editor warmed from the FIXTURE prime
(`tests/fixtures/prime/`, placeholders, no consumer's project) and the same
set with no prime. The runner for the set is built by the editor's build
straight after a `python`-only runner, from the same warm cache, with no
cache filter: the sequence that once left `/opt` empty.
Every container runs with `--network none`. Plants go into `.work/`
(git-ignored), and every container, volume and planted image is removed
afterwards — the two real editor images too, unless `TC_KEEP_IMAGES=1`.
"""

from __future__ import annotations

import os
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
RUNNER_BUILD = ROOT / "docker" / "minimal" / "build.py"
FIXTURE = ROOT / "tests" / "fixtures" / "prime"
WORK = ROOT / ".work" / "tests-prime"
SET = ("gradle", "java", "maven")
PINS = runner_plan.load(ROOT)
READER = "/tmp/reader"


def run(command: list, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in command], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          **kwargs)


def build(prime: Path | None = None, names=SET) -> subprocess.CompletedProcess:
    return run([sys.executable, BUILD, "--runtimes", ",".join(names)] + (["--prime", prime] if prime else []))


def tag(prime: Path | None = None, names=SET) -> str:
    return run([sys.executable, BUILD, "--runtimes", ",".join(names), "--print-tag"]
               + (["--prime", prime] if prime else [])).stdout.strip()


def runner_tag(names) -> str:
    return run([sys.executable, RUNNER_BUILD, "--runtimes", ",".join(names), "--print-tag"]).stdout.strip()


def planted_prime(name: str, keep: str, *remove: str) -> Path:
    """A copy of ONE of the fixture's projects with some of its paths removed."""
    target = WORK / name
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(FIXTURE / keep, target / keep)
    for relative in remove:
        shutil.rmtree(target / keep / relative)
    return target


@unittest.skipUnless(os.environ.get("TC_DOCKER") == "1", "set TC_DOCKER=1 to build and run the images")
class ThePrimedImage(unittest.TestCase):
    containers: list[str] = []
    volumes: list[str] = []
    planted: list[str] = []

    @classmethod
    def setUpClass(cls):
        WORK.mkdir(parents=True, exist_ok=True)
        cls.small, cls.runner = runner_tag(("python",)), runner_tag(SET)
        small = run([sys.executable, RUNNER_BUILD, "--runtimes", "python"])
        assert small.returncode == 0, small.stderr[-3000:]
        # The set's runner is built by the editor's build from the warm cache the
        # small one just left, as once measured, never reused from before.
        run(["docker", "image", "rm", "-f", cls.runner])
        for label, prime in (("primed", FIXTURE), ("bare", None)):
            built = build(prime)
            if built.returncode != 0:
                raise AssertionError(f"the {label} editor did not build:\n{built.stdout[-4000:]}{built.stderr[-2000:]}")
        cls.image, cls.bare = tag(FIXTURE), tag()
        cls.editor = cls.start(cls.image)
        assert cls.wait_for(cls.editor, "maven repository seeded"), cls.logs(cls.editor)
        copied = run(["docker", "cp", f"{FIXTURE}/.", f"{cls.editor}:{READER}"])
        assert copied.returncode == 0, copied.stderr
        cls.exec(cls.editor, "chown", "-R", "1000:1000", READER, user="0")

    @classmethod
    def tearDownClass(cls):
        for name in cls.containers:
            run(["docker", "rm", "-f", name])
        for name in cls.volumes:
            run(["docker", "volume", "rm", "-f", name])
        images = list(cls.planted)
        if os.environ.get("TC_KEEP_IMAGES") != "1":
            images += [cls.image, cls.bare]
        for image in images:
            run(["docker", "image", "rm", "-f", image])
        shutil.rmtree(WORK, ignore_errors=True)

    # ------------------------------------------------------------ helpers
    @classmethod
    def start(cls, image: str, *extra: str) -> str:
        name = f"tc03-prime-{uuid.uuid4().hex[:8]}"
        cls.containers.append(name)
        started = run(["docker", "run", "-d", "--name", name, "--network", "none", *extra, image])
        assert started.returncode == 0, started.stderr
        return name

    @classmethod
    def volume(cls) -> str:
        name = f"tc03-prime-{uuid.uuid4().hex[:8]}"
        cls.volumes.append(name)
        run(["docker", "volume", "create", name])
        return name

    @staticmethod
    def exec(container: str, *command: str, user: str | None = None) -> subprocess.CompletedProcess:
        return run(["docker", "exec", *(["-u", user] if user else []), container, *command])

    @staticmethod
    def logs(container: str) -> str:
        logs = run(["docker", "logs", container])
        return logs.stdout + logs.stderr

    @classmethod
    def wait_for(cls, container: str, needle: str, seconds: int = 180) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if needle in cls.logs(container):
                return True
            time.sleep(1)
        return False

    def shell(self, script: str) -> subprocess.CompletedProcess:
        """The reader's integrated terminal: a login shell as the runtime uid."""
        return self.exec(self.editor, "bash", "-lc", script)

    # ---------------------------------------------------------- acceptance
    def test_a_first_gradle_build_offline_succeeds_and_every_compile_and_test_task_runs(self):
        built = self.shell(f"cd {READER}/gradle && gradle build --offline --no-daemon --console=plain")
        self.assertEqual(built.returncode, 0, built.stdout[-3000:] + built.stderr[-2000:])
        self.assertIn("BUILD SUCCESSFUL", built.stdout)
        for task in (":java:compileJava", ":java:test", ":kotlin:compileKotlin", ":kotlin:test"):
            self.assertRegex(built.stdout, rf"(?m)^> Task {task}$")

    def test_a_first_mvn_offline_test_succeeds_with_what_the_pom_declares_and_no_test_uses(self):
        tested = self.shell(f"cd {READER}/maven && mvn -B -o test")
        self.assertEqual(tested.returncode, 0, tested.stdout[-3000:])
        self.assertIn("Tests run: 1, Failures: 0, Errors: 0, Skipped: 0", tested.stdout)
        declared = self.shell("ls ~/.m2/repository/org/assertj/assertj-core")
        self.assertEqual(declared.stdout.split(), ["3.26.3"])

    def test_without_the_seed_the_same_builds_fail_offline(self):
        """The other way: it is the seed, not something else in the image, that made them work."""
        gradle = self.shell(f"cp -r {READER}/gradle /tmp/g && cd /tmp/g && GRADLE_USER_HOME=/tmp/empty-home "
                            "gradle build --offline --no-daemon --console=plain")
        self.assertNotEqual(gradle.returncode, 0)
        maven = self.shell(f"cp -r {READER}/maven /tmp/m && cd /tmp/m && mvn -B -o -Dmaven.repo.local=/tmp/empty test")
        self.assertNotEqual(maven.returncode, 0)

    def test_the_seed_goes_only_into_an_empty_directory_and_is_owned_by_the_reader(self):
        owner = self.exec(self.editor, "stat", "-c", "%u", "/home/coder/.gradle/caches", "/home/coder/.m2/repository")
        self.assertEqual(owner.stdout.split(), ["1000", "1000"])
        home = self.volume()
        first = self.start(self.image, "-v", f"{home}:/home/coder/.gradle")
        self.assertTrue(self.wait_for(first, "gradle home seeded"), self.logs(first))
        self.exec(first, "sh", "-c", "echo mine > /home/coder/.gradle/marker")
        run(["docker", "rm", "-f", first])
        second = self.start(self.image, "-v", f"{home}:/home/coder/.gradle")
        self.assertTrue(self.wait_for(second, "leaving it alone"), self.logs(second))
        self.assertEqual(self.exec(second, "cat", "/home/coder/.gradle/marker").stdout.strip(), "mine")

    def test_an_image_built_with_no_prime_holds_and_seeds_nothing(self):
        self.assertNotEqual(self.bare, self.image, "the prime's digest is part of the tag")
        held = run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "ls", self.bare,
                    "/opt/code-server/prime"])
        self.assertNotEqual(held.returncode, 0)
        bare = self.start(self.bare)
        self.assertTrue(self.wait_for(bare, "no maven repository seed in this image; skipping"), self.logs(bare))

    def test_a_warm_cache_serves_the_sets_runner_its_own_layers_with_no_cache_filter(self):
        """The set's runner came from the small runner's warm cache, and holds exactly its trees."""
        expected = " ".join(runner_plan.opt_dirs(SET))
        for image in (self.runner, self.image):
            with self.subTest(image=image):
                held = run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "sh", image, "-c",
                            "LC_ALL=C ls -A /opt | grep -vx code-server | xargs"])
                self.assertEqual(held.stdout.strip(), expected)
        small = run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "sh", self.small, "-c",
                     "LC_ALL=C ls -A /opt | xargs"])
        self.assertEqual(small.stdout.strip(), " ".join(runner_plan.opt_dirs(("python",))))

    # ------------------------------------------------------------- refusals
    def planted_build_fails(self, prime: Path, *needles: str) -> None:
        self.planted.append(tag(prime))
        built = build(prime)
        self.assertNotEqual(built.returncode, 0, "the planted build succeeded")
        for needle in needles:
            self.assertIn(needle, built.stdout + built.stderr)

    def test_a_gradle_prime_with_no_sources_fails_the_build_naming_the_project_and_why(self):
        prime = planted_prime("gradle-no-sources", "gradle", "java/src", "kotlin/src")
        self.planted_build_fails(prime, "gradle project :java ran no main compile task",
                                 "gradle project :kotlin ran no test task", "never resolves its classpath")

    def test_a_maven_prime_with_no_sources_fails_the_build_naming_the_module_and_why(self):
        prime = planted_prime("maven-no-sources", "maven", "src")
        self.planted_build_fails(prime, "the maven prime compiled no source",
                                 "the maven prime ran no test")

    def test_a_version_mismatch_is_refused_before_docker_starts_naming_why(self):
        prime = planted_prime("kotlin-mismatch", "gradle")
        path = prime / "gradle" / "kotlin" / "build.gradle.kts"
        kotlin = PINS["runtimes"]["kotlin"]["version"]
        path.write_text(path.read_text(encoding="utf-8").replace(f'"{kotlin}"', '"2.3.0"'), encoding="utf-8")
        refused = build(prime)
        self.assertEqual(refused.returncode, 2, refused.stderr)
        self.assertIn(f"names the Kotlin plugin 2.3.0, and the image's Kotlin is {kotlin}", refused.stderr)


if __name__ == "__main__":
    unittest.main()
