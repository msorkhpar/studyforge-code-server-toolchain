"""Both builds take `--pull never`, and then fetch no image.

Run from the component root: `python3 -m unittest tests.test_pull -v`.

⭐ **What is held, with no Docker.** Every image a build starts FROM is named
by `base_images`, and that is exactly the set of build args the two
Dockerfiles' `FROM ${...}` lines read, so a new base cannot escape the check.
Under `never` an absent base is refused by name before any `docker build`
runs, the command says `--pull=false`, and under `missing` (the default)
nothing is asked and the command is what it always was.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
EDITOR = ROOT / "docker" / "editor"
sys.path.insert(0, str(EDITOR))
sys.path.insert(0, str(ROOT / "docker" / "minimal"))

import build as runner_build  # noqa: E402
import editor_plan  # noqa: E402

_spec = importlib.util.spec_from_file_location("editor_build_pull", EDITOR / "build.py")
editor_build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(editor_build)

AMD64 = "linux/amd64"
NAMES = ["java", "maven"]
#: A `FROM ${ARG}` line's argument.
FROM_ARG = re.compile(r"^FROM \$\{([A-Z_]+)\}", re.MULTILINE)


def runner() -> runner_build.planning.Plan:
    return runner_build.planned(ROOT, AMD64, NAMES)


def editor() -> editor_plan.EditorPlan:
    return editor_build.planned(ROOT, AMD64, NAMES)


def from_args(dockerfile: str) -> set[str]:
    return set(FROM_ARG.findall((ROOT / dockerfile).read_text(encoding="utf-8")))


class TheBases(unittest.TestCase):
    def test_the_runner_bases_are_every_image_its_dockerfile_starts_from(self):
        built = runner()
        wanted = {built.build_args[arg] for arg in from_args(runner_build.planning.DOCKERFILE)}
        self.assertTrue(wanted, "the runner's Dockerfile starts FROM no build arg, so nothing is checked")
        self.assertEqual(set(runner_build.base_images(built)), wanted)

    def test_the_editor_bases_are_every_image_its_dockerfile_starts_from(self):
        built = editor()
        wanted = {built.build_args[arg] for arg in from_args(editor_plan.DOCKERFILE)}
        self.assertIn(built.build_args["RUNNER_IMAGE"], wanted)
        self.assertEqual(set(runner_build.base_images(built)), wanted)


class ThePolicy(unittest.TestCase):
    def test_never_refuses_an_absent_image_by_name(self):
        said = runner_build.pull_refusal(["a/one@sha256:1", "a/two@sha256:2"], "never",
                                         present=lambda image: image.startswith("a/one"))
        self.assertIsNotNone(said)
        self.assertIn("a/two@sha256:2", said)
        self.assertNotIn("a/one", said)

    def test_never_with_every_image_present_builds(self):
        self.assertIsNone(runner_build.pull_refusal(["a/one"], "never", present=lambda image: True))

    def test_missing_asks_nothing(self):
        asked = []
        self.assertIsNone(runner_build.pull_refusal(["a/one"], "missing", present=asked.append))
        self.assertEqual(asked, [])

    def test_the_command_says_it_only_under_never(self):
        built = runner()
        self.assertIn("--pull=false", runner_build.docker_command(ROOT, built, pull="never"))
        self.assertFalse([word for word in runner_build.docker_command(ROOT, built) if word.startswith("--pull")])
        self.assertIn("--pull=false", editor_build.runner_command(ROOT, AMD64, NAMES, pull="never"))
        self.assertIn("--pull=false", editor_build.docker_command(ROOT, editor(), ROOT, pull="never"))


class TheBuilds(unittest.TestCase):
    """The two `main`s under `never`, with Docker stood in for: refused before any build."""

    def ran(self, main, argv):
        started = []

        def run(command, **_kwargs):
            started.append(command)
            return mock.Mock(returncode=0)

        with mock.patch.object(runner_build, "image_present", return_value=False), \
                mock.patch.object(runner_build.subprocess, "run", side_effect=run), \
                mock.patch.object(editor_build.subprocess, "run", side_effect=run), \
                mock.patch("sys.stderr") as err:
            code = main(argv)
        said = "".join(call.args[0] for call in err.write.call_args_list)
        return code, said, started

    def test_the_runner_under_never_builds_nothing_when_a_base_is_absent(self):
        code, said, started = self.ran(runner_build.main, ["--runtimes", "java,maven", "--pull", "never"])
        self.assertEqual(code, 2)
        self.assertIn("--pull never and this host lacks", said)
        self.assertEqual(started, [])

    def test_the_editor_under_never_builds_nothing_when_a_base_is_absent(self):
        code, said, started = self.ran(editor_build.main, ["--runtimes", "java,maven", "--pull", "never"])
        self.assertEqual(code, 2)
        for image in runner_build.base_images(runner()):
            self.assertIn(image, said, "the runner's own bases are checked before the runner is built")
        self.assertEqual(started, [])


if __name__ == "__main__":
    unittest.main()
