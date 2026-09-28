"""The builds as data, and the course layer they describe.

Run from the component root: `python3 -m unittest tests.test_builds -v`.

⭐ Every assertion here is about the plans' OWN values: a tag `builds.py`
prints is the tag `build.py` computes, an ARG it prints is one the Dockerfile
reads, and a course layer holds its caches where the primed images hold theirs.
⛔ No Docker: `tests/test_prime_image.py` and its siblings build images.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "consuming"))
import builds  # noqa: E402

runner_plan = builds.runner_plan
editor_plan = builds.editor_plan
FIXTURE = ROOT / "tests" / "fixtures" / "prime"
CONTRACT = json.loads((ROOT / "consuming.json").read_text(encoding="utf-8"))
LAYER = (ROOT / builds.LAYER_DOCKERFILE).read_text(encoding="utf-8")
PLATFORM = "linux/amd64"
SET = ("java", "maven")


def maven_prime(tmp: str) -> Path:
    """The fixture's maven project alone: a prime the java,maven set can warm."""
    prime = Path(tmp) / "prime"
    shutil.copytree(FIXTURE / "maven", prime / "maven")
    return prime


def load_build(relative: str, name: str):
    """One of the build scripts, loaded by path: both are called `build.py`."""
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stage_args(text: str, target: str) -> set[str]:
    """Every ARG one stage of a Dockerfile reads, and the global ARGs before the first FROM."""
    stages = re.split(r"(?m)^FROM ", text)
    head = set(re.findall(r"(?m)^ARG (\w+)", stages[0]))
    for stage in stages[1:]:
        if re.match(rf"\S+ AS {re.escape(target)}\b", stage):
            return head | set(re.findall(r"(?m)^ARG (\w+)", stage))
    raise AssertionError(f"no stage {target}")


class TheTagsAreTheBuildsOwn(unittest.TestCase):
    def test_the_runner_and_the_editor_print_the_tags_build_py_computes(self):
        runner_build = load_build("docker/minimal/build.py", "runner_build")
        editor_build = load_build("docker/editor/build.py", "editor_build")
        with tempfile.TemporaryDirectory() as tmp:
            prime = maven_prime(tmp)
            for read in (None, prime):
                with self.subTest(primed=read is not None):
                    runner = builds.described(ROOT, "runner", SET, PLATFORM, read)
                    editor = builds.described(ROOT, "editor", SET, PLATFORM, read)
                    self.assertEqual(runner["tag"], runner_build.planned(ROOT, PLATFORM, list(SET), read).tag)
                    self.assertEqual(editor["tag"], editor_build.planned(ROOT, PLATFORM, list(SET), read).tag)
                    self.assertEqual(editor["args"], editor_build.planned(ROOT, PLATFORM, list(SET), read).build_args)

    def test_the_editor_names_the_unprimed_runner_it_starts_from_as_one_built_here(self):
        editor = builds.described(ROOT, "editor", SET, PLATFORM)
        runner = builds.described(ROOT, "runner", SET, PLATFORM)
        self.assertEqual(editor["built_here"], {"RUNNER_IMAGE": "runner"})
        self.assertEqual(editor["from"]["RUNNER_IMAGE"], runner["tag"])
        self.assertEqual(editor["proved_by"], builds.EDITOR_PROOFS)
        self.assertEqual(runner["proved_by"], [])

    def test_every_image_a_build_starts_from_that_it_does_not_build_is_pinned_by_digest(self):
        for image in ("runner", "editor"):
            document = builds.described(ROOT, image, SET, PLATFORM)
            for key, value in document["from"].items():
                if key not in document["built_here"]:
                    with self.subTest(image=image, key=key):
                        self.assertRegex(value, r"@sha256:[0-9a-f]{64}$")


class TheCourseLayer(unittest.TestCase):
    def test_a_layer_starts_from_the_unprimed_base_and_warms_what_the_primed_runner_warms(self):
        with tempfile.TemporaryDirectory() as tmp:
            prime = maven_prime(tmp)
            read = builds.prime_contract.read(prime)
            for image in ("runner", "editor"):
                with self.subTest(image=image):
                    layer = builds.described(ROOT, f"{image}-prime", SET, PLATFORM, prime)
                    base = builds.described(ROOT, image, SET, PLATFORM)
                    self.assertEqual(layer["args"]["BASE_IMAGE"], base["tag"])
                    self.assertEqual(layer["built_here"], {"BASE_IMAGE": image})
                    self.assertTrue(layer["tag"].startswith(base["tag"] + "-prime-"))
                    self.assertEqual(layer["args"]["PRIME_KEY"], read.digest)
                    self.assertEqual(layer["args"]["WITH_MAVEN_PRIME"], "yes")
                    self.assertEqual(layer["args"]["WITH_GRADLE_PRIME"], "no")
                    self.assertEqual(layer["contexts"], {"consumer-prime": "prime"})
            primed = builds.described(ROOT, "runner", SET, PLATFORM, prime)["args"]
            layer = builds.described(ROOT, "runner-prime", SET, PLATFORM, prime)["args"]
            for key in ("PRIME_MAVEN_ARGS", "PRIME_GRADLE_HOME"):
                self.assertEqual(layer[key], primed[key], key)

    def test_another_prime_is_another_layer_tag_on_the_same_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            prime = maven_prime(tmp)
            before = builds.described(ROOT, "runner-prime", SET, PLATFORM, prime)["tag"]
            pom = prime / "maven" / "pom.xml"
            pom.write_text(pom.read_text(encoding="utf-8") + "\n<!-- another course -->\n", encoding="utf-8")
            after = builds.described(ROOT, "runner-prime", SET, PLATFORM, prime)["tag"]
        self.assertNotEqual(before, after)
        self.assertEqual(before.split("-prime-")[0], after.split("-prime-")[0])

    def test_a_layer_with_no_prime_is_refused_by_name(self):
        with self.assertRaisesRegex(builds.Refused, "--prime"):
            builds.described(ROOT, "editor-prime", SET, PLATFORM)

    def test_every_arg_each_layer_reads_is_printed_and_every_printed_arg_is_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            prime = maven_prime(tmp)
            for image in ("runner-prime", "editor-prime"):
                with self.subTest(image=image):
                    printed = set(builds.described(ROOT, image, SET, PLATFORM, prime)["args"])
                    read = stage_args(LAYER, image)
                    if image == "editor-prime":
                        printed -= {"PRIME_GRADLE_HOME", "PRIME_MAVEN_ARGS"}
                    self.assertEqual(read, printed)

    def test_the_arg_reading_catches_a_stage_that_reads_one_nobody_prints(self):
        planted = LAYER.replace("ARG PRIME_KEY", "ARG PRIME_KEY\nARG A_NEW_SWITCH", 1)
        self.assertIn("A_NEW_SWITCH", stage_args(planted, "runner-prime"))

    def test_each_layer_warms_into_the_seed_root_its_primed_image_uses(self):
        runner_root = CONTRACT["runner"]["prime"]["root"]
        editor_root = CONTRACT["editor"]["prime"]["root"]
        self.assertEqual(runner_root, runner_plan.PRIME_ROOT)
        self.assertEqual(CONTRACT["course_layer"]["prime_roots"], {"runner": runner_root, "editor": editor_root})
        runner_stage, editor_stage = LAYER.split("AS editor-prime", 1)
        for tool, seed in CONTRACT["runner"]["prime"]["seeds"].items():
            with self.subTest(tool=tool):
                self.assertIn(f"warm-{tool}.sh warm /tmp/prime/{tool} {runner_root}/{seed}", runner_stage)
                self.assertIn(f"warm-{tool}.sh prove /tmp/prime/{tool} {runner_root}/{seed}", runner_stage)
                self.assertIn(f"warm-{tool}.sh warm /tmp/prime/{tool} {editor_root}/{seed}", editor_stage)
                self.assertIn(f"warm-{tool}.sh prove /tmp/prime/{tool} {editor_root}/{seed}", editor_stage)
        self.assertTrue(editor_stage.rstrip().endswith("USER 1000"), "the editor layer hands the image back")

    def test_the_contracts_scheme_is_the_tag_the_layer_computes(self):
        with tempfile.TemporaryDirectory() as tmp:
            prime = maven_prime(tmp)
            layer = builds.described(ROOT, "runner-prime", SET, PLATFORM, prime)
        base, _, inputs = layer["tag"].rpartition("-prime-")
        scheme = CONTRACT["course_layer"]["tag"]["scheme"]
        self.assertEqual(scheme.format(base=base, inputs=inputs), layer["tag"])
        self.assertEqual(len(inputs), 12)


class TheDocument(unittest.TestCase):
    def test_it_prints_no_path_of_the_host_and_names_only_inputs_that_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            prime = maven_prime(tmp)
            for image in builds.TARGETS:
                document = builds.described(ROOT, image, SET, PLATFORM,
                                            prime if image.endswith("prime") else None)
                text = json.dumps(document)
                with self.subTest(image=image):
                    self.assertNotIn(str(ROOT), text)
                    self.assertNotIn(tmp, text)
                    self.assertEqual(sorted(document), sorted(CONTRACT["builds"]["keys"]))
                    self.assertEqual(document["builds_api"], CONTRACT["builds"]["builds_api"])
                    for entry in document["inputs"]:
                        self.assertTrue((ROOT / entry).exists(), entry)
                    self.assertTrue((ROOT / document["dockerfile"]).is_file())

    def test_the_layer_dockerfile_is_no_build_input_so_it_moves_no_tag(self):
        inputs = set(CONTRACT["editor"]["image"]["tag"]["build_inputs"]) | set(
            CONTRACT["runner"]["image"]["tag"]["build_inputs"])
        for path in (builds.LAYER_DOCKERFILE, "consuming/builds.py"):
            with self.subTest(path=path):
                self.assertFalse(any(path == entry or path.startswith(entry + "/") for entry in inputs))


if __name__ == "__main__":
    unittest.main()
