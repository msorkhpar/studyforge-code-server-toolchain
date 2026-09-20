"""The runner image, built and run for real — every assertion BOTH ways.

⛔ Skipped unless `TC_DOCKER=1`: it builds images and starts containers. Run
it as ONE container job (the whole module under whatever lock the host uses):

    TC_DOCKER=1 python3 -m unittest tests.test_image -v

Plants go into temporary copies under `.work/` (git-ignored, inside this
repository so a build context never lands on a RAM-backed /tmp), and the
images this module builds are removed afterwards unless `TC_KEEP_IMAGES=1`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "docker" / "minimal"))

import build_inputs  # noqa: E402
import plan  # noqa: E402

BUILD = ROOT / "docker" / "minimal" / "build.py"
WORK = ROOT / ".work" / "tests"
PINS = plan.load(ROOT)
EVERYTHING = sorted(PINS["runtimes"])
BINARIES = {
    "java": ["java", "javac"], "maven": ["mvn"], "gradle": ["gradle"], "kotlin": ["kotlinc"],
    "node": ["node"], "python": ["python3", "pytest"], "sqlite": ["sqlite3"], "shell": ["bash"],
}
#: What the base brings to EVERY image, declared or not — named so an absence
#: assertion never pretends otherwise (W374).
BASE_TOOLS = {"shell"}
#: One image per runtime in the vocabulary: the runtime and what it runs on.
SINGLES = sorted({tuple(sorted({name, *PINS["runtimes"][name].get("requires", [])})) for name in EVERYTHING})
#: A LARGE set built AFTER the singles, `python` among them: the order that served
#: a five-runtime build the `python`-only build's layers and left /opt empty
#: (W379, TC-01/13). EVERYTHING before the singles is the other direction (W374).
LATE = ["gradle", "java", "kotlin", "node", "python"]


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, **kwargs)


def build(names: list[str], root: Path = ROOT) -> subprocess.CompletedProcess:
    return run([sys.executable, str(BUILD), "--root", str(root), "--runtimes", ",".join(names)])


def tag(names: list[str], root: Path = ROOT) -> str:
    return run([sys.executable, str(BUILD), "--root", str(root), "--runtimes", ",".join(names), "--print-tag"]).stdout.strip()


def in_image(image: str, script: str, login: bool = False) -> subprocess.CompletedProcess:
    shell = ["bash", "-lc", script] if login else ["sh", "-c", script]
    return run(["docker", "run", "--rm", "--network", "none", image, *shell])


def planted_copy(name: str) -> Path:
    """A copy of the build's inputs, to plant a defect in without touching the tree."""
    return build_inputs.copy_inputs(WORK / name, inputs=plan.INPUT_ROOTS)


def rewrite_pins(root: Path, mutate) -> None:
    path = root / "pins.json"
    pins = json.loads(path.read_text(encoding="utf-8"))
    mutate(pins)
    path.write_text(json.dumps(pins, indent=2) + "\n", encoding="utf-8")


@unittest.skipUnless(os.environ.get("TC_DOCKER") == "1", "set TC_DOCKER=1 to build and run the image")
class TheRunnerImage(unittest.TestCase):
    built: list[str] = []

    @classmethod
    def setUpClass(cls):
        WORK.mkdir(parents=True, exist_ok=True)
        # ⭐ EVERYTHING first, on purpose: it is the build that left BuildKit's
        # cache holding every runtime on the python base, which a `python`-only
        # build then came out carrying (W374). The singles are built after it.
        cls.singles = {}
        for names in [EVERYTHING] + [list(names) for names in SINGLES] + [LATE]:
            result = build(names)
            if result.returncode != 0:
                raise RuntimeError(f"the build of {names} failed:\n{result.stdout[-4000:]}{result.stderr[-4000:]}")
            cls.built.append(tag(names))
            cls.singles[tuple(names)] = tag(names)
        cls.full, cls.shell_only = cls.built[0], cls.singles[("shell",)]

    @classmethod
    def tearDownClass(cls):
        if os.environ.get("TC_KEEP_IMAGES") != "1":
            for image in cls.built:
                run(["docker", "image", "rm", image])
        shutil.rmtree(WORK, ignore_errors=True)

    # -- present at the pinned version, and absent when not declared ----------
    def test_every_declared_runtime_reports_its_pinned_version(self):
        for name, entry in PINS["runtimes"].items():
            for check in entry["checks"]:
                expect = check["expect"].format(version=entry["version"])
                with self.subTest(runtime=name, command=check["command"]):
                    result = in_image(self.full, f"{check['command']} 2>&1")
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn(expect, result.stdout)

    def test_an_undeclared_runtime_is_absent_and_a_declared_one_is_present(self):
        for name, binaries in BINARIES.items():
            for binary in binaries:
                with self.subTest(binary=binary):
                    self.assertEqual(in_image(self.full, f"command -v {binary}").returncode, 0)
                    if name != "shell":
                        self.assertNotEqual(in_image(self.shell_only, f"command -v {binary}").returncode, 0)
        self.assertEqual(in_image(self.shell_only, "ls /opt").stdout.strip(), "")

    def test_every_runtime_alone_builds_an_image_holding_exactly_its_declared_set(self):
        """W374: for EVERY runtime in the vocabulary, present iff declared or the base's own."""
        for names, image in self.singles.items():
            with self.subTest(declared=names):
                label = run(["docker", "image", "inspect", "--format",
                             '{{index .Config.Labels "org.studyforge.runner.runtimes"}}', image])
                self.assertEqual(label.stdout.split(), list(names))
                held = in_image(image, "ls -A /opt | xargs").stdout.strip()
                self.assertEqual(held, " ".join(plan.opt_dirs(names)), f"{image} holds /opt: {held}")
                for runtime, binaries in BINARIES.items():
                    expect = runtime in names or runtime in BASE_TOOLS
                    for binary in binaries:
                        with self.subTest(runtime=runtime, binary=binary, expect=expect):
                            found = in_image(image, f"command -v {binary}").returncode == 0
                            self.assertEqual(found, expect)

    def test_a_large_set_built_after_a_small_one_holds_exactly_its_declared_set(self):
        """W379: small then large, from the cache the singles just warmed; the reverse is W374's case."""
        image = self.singles[tuple(LATE)]
        self.assertIn(("python",), self.singles, "the small set was built first")
        held = in_image(image, "ls -A /opt | xargs").stdout.strip()
        self.assertEqual(held, " ".join(plan.opt_dirs(LATE)))
        for runtime in LATE:
            for binary in BINARIES[runtime]:
                with self.subTest(binary=binary):
                    self.assertEqual(in_image(image, f"command -v {binary}").returncode, 0)

    def test_every_image_was_built_under_its_own_tag_as_the_cache_key(self):
        """W379: the runner's keyed RUN carries the image's own tag, so its layers are cached per tag."""
        for image in self.built:
            with self.subTest(image=image):
                history = run(["docker", "history", "--no-trunc", "--format", "{{.CreatedBy}}", image]).stdout
                keyed = [line for line in history.splitlines() if 'runner ${CACHE_KEY}' in line]
                self.assertEqual(len(keyed), 1, history[-2000:])
                self.assertIn(f"CACHE_KEY={image} ", keyed[0])

    def test_a_login_shell_finds_the_same_tools(self):
        result = in_image(self.full, "command -v mvn && command -v node && command -v kotlinc", login=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_image_carries_no_editor_no_docker_and_no_socket(self):
        for image in self.built:
            for probe in ("command -v code-server", "command -v docker", "test -e /var/run/docker.sock"):
                with self.subTest(image=image, probe=probe):
                    self.assertNotEqual(in_image(image, probe).returncode, 0)
        labels = run(["docker", "image", "inspect", "--format", "{{json .Config.ExposedPorts}}", self.full])
        self.assertEqual(labels.stdout.strip(), "null")

    # -- every smoke project, offline, as the reader's uid ---------------------
    def test_each_smoke_project_passes_offline_and_its_planted_failure_fails(self):
        for path in sorted((ROOT / "docker" / "minimal" / "smoke").glob("*/smoke.json")):
            smoke = json.loads(path.read_text(encoding="utf-8"))
            for planted in (False, True):
                with self.subTest(smoke=path.parent.name, planted=planted):
                    work = WORK / "smoke" / f"{path.parent.name}-{'planted' if planted else 'clean'}"
                    shutil.rmtree(work, ignore_errors=True)
                    shutil.copytree(path.parent, work)
                    if planted:
                        target = work / smoke["plant"]["file"]
                        text = target.read_text(encoding="utf-8")
                        target.write_text(text.replace(smoke["plant"]["from"], smoke["plant"]["to"]), encoding="utf-8")
                    result = run([
                        "docker", "run", "--rm", "--init", "--network", "none",
                        "--user", f"{os.getuid()}:{os.getgid()}", "-v", f"{work}:/work", self.full,
                        *smoke["command"],
                    ])
                    output = result.stdout + result.stderr
                    if planted:
                        self.assertNotEqual(result.returncode, 0, output)
                    else:
                        self.assertEqual(result.returncode, 0, output)

    # -- the documented run line, and exec from outside -------------------------
    def test_the_documented_run_line_starts_a_container_the_runner_can_exec_into(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        line = next(l for l in plan._joined(readme) if l.lstrip().startswith("docker run"))
        name = f"tc00-{uuid.uuid4().hex[:8]}"
        work = WORK / "exec"
        shutil.rmtree(work, ignore_errors=True)
        shutil.copytree(ROOT / "docker" / "minimal" / "smoke" / "node", work)
        line = (line.replace("studyforge-runner-<source>", name).replace("<source root>", str(work))
                .replace("<tag>", self.full).replace("$(id -u):$(id -g)", f"{os.getuid()}:{os.getgid()}"))
        started = subprocess.run(line, shell=True, stdin=subprocess.DEVNULL, capture_output=True, text=True)
        try:
            self.assertEqual(started.returncode, 0, started.stderr)
            inspected = run(["docker", "inspect", "--format",
                             "{{.HostConfig.NetworkMode}} {{json .HostConfig.PortBindings}} {{json .Mounts}}", name])
            self.assertTrue(inspected.stdout.startswith("none "), inspected.stdout)
            self.assertNotIn("docker.sock", inspected.stdout)
            passed = run(["docker", "exec", "-w", "/work", name, "node", "--test"])
            self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
            (work / "smoke.test.js").write_text(
                (work / "smoke.test.js").read_text(encoding="utf-8").replace("1 + 1, 2", "1 + 1, 3"), encoding="utf-8")
            failed = run(["docker", "exec", "-w", "/work", name, "node", "--test"])
            self.assertNotEqual(failed.returncode, 0)
        finally:
            run(["docker", "rm", "-f", name])

    # -- a pin the fetched bytes disagree with stops the build -------------------
    def test_a_wrong_checksum_stops_the_build_before_anything_is_unpacked(self):
        root = planted_copy("wrong-checksum")
        rewrite_pins(root, lambda p: p["runtimes"]["node"]["archives"]["amd64"].update(sha256="0" * 64)
                     or p["runtimes"]["node"]["archives"]["arm64"].update(sha256="0" * 64))
        result = build(["node"], root)
        self.assertNotEqual(result.returncode, 0)
        self.assertRegex(result.stdout + result.stderr, re.compile("checksum", re.I))
        self.assertEqual(build(["node"], planted_copy("right-checksum")).returncode, 0)
        # The copy's inputs are the tree's, so its tag is the `node` image the class built
        # and still reads; only an image the class did not build is removed here.
        if tag(["node"], WORK / "right-checksum") not in self.built:
            run(["docker", "image", "rm", tag(["node"], WORK / "right-checksum")])

    def test_a_version_the_runtime_does_not_report_stops_the_build(self):
        root = planted_copy("wrong-version")
        rewrite_pins(root, lambda p: p["runtimes"]["node"].update(version="24.21.1"))
        result = build(["node"], root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not report", result.stdout + result.stderr)

    def test_an_undeclared_runtime_under_opt_stops_the_build(self):
        """W374: the build refuses an image whose /opt is not the declared set's."""
        root = planted_copy("undeclared-opt")
        dockerfile = root / "docker" / "minimal" / "Dockerfile"
        stage = "FROM scratch AS node-no\nWORKDIR /opt\n"
        text = dockerfile.read_text(encoding="utf-8")
        self.assertIn(stage, text)
        dockerfile.write_text(text.replace(stage, stage + "COPY pins.json /opt/node/planted\n"), encoding="utf-8")
        result = build(["python"], root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("/opt holds 'node'; the declared set places ''", result.stdout + result.stderr)

    def test_a_warm_file_that_differs_from_its_pin_stops_the_build(self):
        plants = {
            "a changed hash": lambda files: files.update({next(iter(sorted(files))): "0" * 64}),
            "an unpinned file": lambda files: files.pop(next(iter(sorted(files)))),
        }
        for label, mutate in plants.items():
            with self.subTest(plant=label):
                root = planted_copy("warm-" + label.replace(" ", "-"))
                rewrite_pins(root, lambda p: mutate(p["runtimes"]["maven"]["warm"]["files"]))
                result = build(["java", "maven"], root)
                self.assertNotEqual(result.returncode, 0)
                self.assertRegex(result.stdout + result.stderr, "checksum differs from pins.json|unpinned file")


if __name__ == "__main__":
    unittest.main()
