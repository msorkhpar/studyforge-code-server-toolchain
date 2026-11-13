"""The `optimization` profile: every input pinned and checksummed, planned and refused before Docker starts.

Run from the component root: `python3 -m unittest tests.test_profile_optimization -v`.

Held: the profile layers on the node-python base and names both images, OpenSpec 2.0.0 is put on PATH from
a lockfile with its version checked, proved as a non-root user and run with telemetry off, its tag has the profile form,
nothing in it is waiting to be pinned, the solver versions are the ones the course reads (including the
two deliberate holds: highspy 1.14.0 and PuLP 3.3.2), every requirement carries exactly one hash, a
changed checksum is refused by the entry's name before Docker starts, and the profile moves no base tag
and no other profile's tag.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "docker" / "profile"))
sys.path.insert(0, str(ROOT / "docker" / "profile_packages"))

import package_build  # noqa: E402
import package_kinds  # noqa: E402
import profile_plan  # noqa: E402
import test_profile as shared  # noqa: E402

NAME = "optimization"
AMD64 = shared.AMD64
DIGEST = shared.IMAGE_DIGEST
REQUIREMENTS = ROOT / "profiles" / NAME / "requirements.txt"


def scratch():
    return tempfile.TemporaryDirectory(dir=ROOT / ".work" if (ROOT / ".work").is_dir() else None)


class ThePlan(unittest.TestCase):
    def test_it_layers_on_python_and_node_and_names_both_images(self):
        profile = profile_plan.load(ROOT, NAME)
        self.assertEqual(profile["layers_on"], ["python", "node"])
        self.assertEqual(profile["images"], ["runner", "editor"])
        self.assertEqual([e["kind"] for e in profile["adds"]], ["python-wheels", "npm-packages", "editor-extension"])

    def test_openspec_is_on_path_checked_proved_and_silent(self):
        built = package_kinds.plan(ROOT, NAME, "runner", [], AMD64)
        self.assertEqual(built.build_args["PROFILE_NPM_BINS"], "openspec|openspec|0|openspec")
        self.assertEqual(built.build_args["PROFILE_NPM_CHECKS"].splitlines(),
                         ["openspec|node --version|v24.21.0", "openspec|openspec --version|2.0.0"])
        self.assertEqual(built.build_args["PROFILE_NPM_PROOFS"], "openspec/proof.sh")
        self.assertEqual(built.build_args["PROFILE_TELEMETRY_OFF"], "1")
        lock = json.loads((ROOT / "profiles" / NAME / "openspec" / "package-lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["packages"][""]["dependencies"], {"@fission-ai/openspec": "2.0.0"})
        self.assertEqual(lock["packages"]["node_modules/@fission-ai/openspec"]["version"], "2.0.0")

    def test_the_node_check_is_the_bases_pinned_node(self):
        pins = json.loads((ROOT / "pins.json").read_text(encoding="utf-8"))
        entry = package_kinds.npm(profile_plan.load(ROOT, NAME))[0]
        self.assertIn({"command": "node --version", "expect": "v" + pins["runtimes"]["node"]["version"]}, entry["checks"])

    def test_the_tag_has_the_profile_form_for_both_images(self):
        runner = package_kinds.plan(ROOT, NAME, "runner", [], AMD64)
        editor = package_kinds.plan(ROOT, NAME, "editor", [], AMD64)
        self.assertRegex(runner.tag, r"^code-server-toolchain/runner-optimization:node-python-amd64-[0-9a-f]{12}$")
        self.assertRegex(editor.tag, r"^code-server-toolchain/editor-optimization:node-python-amd64-[0-9a-f]{12}$")

    def test_a_larger_base_set_is_accepted(self):
        built = package_kinds.plan(ROOT, NAME, "runner", ["gradle", "java", "kotlin", "node", "python"], AMD64)
        self.assertRegex(built.tag, r"^code-server-toolchain/runner-optimization:gradle-java-kotlin-node-python-amd64-")


class TheRealPins(unittest.TestCase):
    def test_nothing_is_waiting_and_every_check_passes(self):
        profile = profile_plan.load(ROOT, NAME)
        self.assertEqual(profile_plan.unpinned(profile), [])
        package_kinds.check(ROOT, NAME, profile, AMD64)

    def test_the_pins_are_the_versions_the_course_reads(self):
        requirements = REQUIREMENTS.read_text(encoding="utf-8")
        for pin in ("ortools==9.15.6755", "highspy==1.14.0", "gurobipy==13.0.3", "pyomo==6.10.1", "pulp==3.3.2",
                    "numpy==2.5.4", "scipy==1.18.1", "pandas==3.1.0", "hypothesis==6.170.13", "fastapi==0.162.0",
                    "httpx==0.28.1", "boto3==1.43.121", "moto==5.2.5", "numpy-financial==1.1.0"):
            self.assertIn(pin + " \\\n", requirements)

    def test_every_requirement_has_exactly_one_hash(self):
        entries = re.findall(r"^(\S+==\S+) \\\n((?:    --hash=sha256:[0-9a-f]{64}(?: \\)?\n)+)",
                             REQUIREMENTS.read_text(encoding="utf-8"), re.M)
        self.assertGreater(len(entries), 50)
        for pin, hashes in entries:
            self.assertEqual(hashes.count("--hash="), 1, pin)

    def test_the_wheels_are_linux_amd64_and_the_solvers_are_imported(self):
        wheels = package_kinds.wheels(profile_plan.load(ROOT, NAME))[0]
        self.assertEqual(wheels["platforms"], ["linux/amd64"])
        for module in ("ortools.math_opt.python.mathopt", "ortools.sat.python.cp_model", "highspy", "gurobipy",
                       "pyomo.environ", "pulp"):
            self.assertIn(module, wheels["imports"])


class TheRefusals(unittest.TestCase):
    def test_a_changed_requirements_file_is_refused_by_the_entry_name(self):
        with scratch() as tmp:
            root = shared.context(tmp)
            with (root / "profiles" / NAME / "requirements.txt").open("a", encoding="utf-8") as handle:
                handle.write("\n")
            err = io.StringIO()
            with mock.patch.object(package_build.subprocess, "run", side_effect=AssertionError("Docker started")), \
                    contextlib.redirect_stderr(err):
                code = package_build.main(["--root", str(root), "--profile", NAME, "--image", "runner",
                                           "--base-digest", DIGEST])
            self.assertEqual(code, 2)
            self.assertIn("python-optimization", err.getvalue())


    def _refused(self, edit) -> str:
        with scratch() as tmp:
            root = shared.context(tmp)
            shared.edit_profile(root, NAME, lambda d: edit(package_kinds.npm(d)[0]))
            err = io.StringIO()
            with mock.patch.object(package_build.subprocess, "run", side_effect=AssertionError("Docker started")), \
                    contextlib.redirect_stderr(err):
                code = package_build.main(["--root", str(root), "--profile", NAME, "--image", "runner",
                                           "--base-digest", DIGEST])
            self.assertEqual(code, 2)
            return err.getvalue()

    def test_a_command_no_locked_package_declares_is_refused(self):
        self.assertIn("'openspecs'", self._refused(lambda e: e.update(bins=["openspecs"])))

    def test_a_check_without_an_expected_answer_is_refused(self):
        self.assertIn("openspec", self._refused(lambda e: e.update(checks=[{"command": "openspec --version"}])))

    def test_a_missing_proof_is_refused(self):
        self.assertIn("is missing", self._refused(lambda e: e.update(proof="openspec/absent.sh")))

    def test_telemetry_off_is_a_boolean(self):
        self.assertIn("telemetry_off", self._refused(lambda e: e.update(telemetry_off="yes")))


class NothingElseMoves(unittest.TestCase):
    def test_the_profile_is_in_no_base_or_other_profiles_tag(self):
        with scratch() as tmp:
            root = shared.context(tmp)
            before_bases = shared.base_tags(root)
            other = package_kinds.plan(root, "claude-sdks", "runner", [], AMD64).tag
            shared.edit_profile(root, NAME, lambda d: d.update(about=d["about"] + " (edited)"))
            self.assertEqual(shared.base_tags(root), before_bases)
            self.assertEqual(package_kinds.plan(root, "claude-sdks", "runner", [], AMD64).tag, other)


if __name__ == "__main__":
    unittest.main()
