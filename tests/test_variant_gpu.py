"""The `optimization-gpu` variant: pinned, planned and refused before Docker starts, and chosen safely.

Run from the component root: `python3 -m unittest tests.test_variant_gpu -v`. No Docker: the chooser's
`docker` calls are replaced by a fake.

Held: the variant has its own tag form and folds the profile's tag; adding or editing it moves no base
tag and no profile tag, and it is not a profile (`package_build.py` refuses it); every pinned file is
checked by its digest and every requirement is hashed once; the CUDA wheels are one closure with cuOpt's
and on one CUDA line; the HiGHS edits refuse a file that is not the pinned one; the recipe keeps the
compiler in its build stage and builds with no network; and the chooser falls back to the CPU image
unless the GPU image is present and the probe passes, with `TOOLCHAIN_VARIANT` forcing either way.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "docker" / "variant_gpu"))
sys.path.insert(0, str(ROOT / "consuming"))
sys.path.insert(0, str(ROOT / "docker" / "minimal"))

import edit_source  # noqa: E402
import plan as runner_rules  # noqa: E402
import test_profile as shared  # noqa: E402
import variant  # noqa: E402
import variant_build  # noqa: E402
import variant_plan  # noqa: E402

NAME = "optimization-gpu"
PROFILE = "optimization"
AMD64 = shared.AMD64
DIGEST = shared.IMAGE_DIGEST
FILES = ROOT / "variants" / NAME
package_kinds = variant_plan.package_kinds


def scratch():
    return tempfile.TemporaryDirectory(dir=ROOT / ".work" if (ROOT / ".work").is_dir() else None)


def context(tmp) -> Path:
    root = shared.context(tmp)
    shutil.copytree(ROOT / "variants", root / "variants")
    return root


def edit_variant(root: Path, change) -> None:
    path = root / "variants" / f"{NAME}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def pins(name: str) -> dict[str, str]:
    return variant_plan.requirement_names((FILES / name).read_text(encoding="utf-8"))


class ThePlan(unittest.TestCase):
    def test_the_tag_has_the_variant_form_and_names_the_profile_it_layers_on(self):
        built = variant_plan.plan(ROOT, NAME, "runner", [], AMD64)
        self.assertRegex(built.tag, r"^code-server-toolchain/runner-optimization-gpu:node-python-amd64-[0-9a-f]{12}$")
        self.assertEqual(built.profile_tag, package_kinds.plan(ROOT, PROFILE, "runner", [], AMD64).tag)
        self.assertEqual(built.published, "studyforge-code-toolchain-runner-optimization-gpu")
        self.assertEqual(built.build_args["PROFILE_IMAGE"], built.profile_tag)

    def test_it_is_built_for_the_runner_and_for_amd64_only(self):
        with self.assertRaises(variant_plan.Refused):
            variant_plan.plan(ROOT, NAME, "editor", [], AMD64)
        with self.assertRaises(variant_plan.Refused):
            variant_plan.check(ROOT, NAME, variant_plan.load(ROOT, NAME), shared.ARM64)

    def test_the_print_tag_command_prints_one_line(self):
        done = subprocess.run([sys.executable, "docker/variant_gpu/variant_build.py", "--variant", NAME, "--image", "runner",
                               "--print-tag"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), variant_plan.plan(ROOT, NAME, "runner", [], AMD64).tag)

    def test_it_is_not_a_profile(self):
        self.assertFalse((ROOT / "profiles" / f"{NAME}.json").exists())
        done = subprocess.run([sys.executable, "docker/profile_packages/package_build.py", "--profile", NAME, "--image",
                               "runner", "--print-tag"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stdout, "")


class NothingElseMoves(unittest.TestCase):
    def test_editing_the_variant_moves_no_base_and_no_profile_tag(self):
        with scratch() as tmp:
            root = context(tmp)
            bases = shared.base_tags(root)
            profiles = {p: package_kinds.plan(root, p, "runner", ["node", "python"], AMD64).tag for p in (PROFILE,)}
            before = variant_plan.plan(root, NAME, "runner", [], AMD64).tag
            edit_variant(root, lambda d: d.update(about=d["about"] + " (edited)"))
            (root / "docker" / "variant_gpu" / "proof.py").write_text("# edited\n", encoding="utf-8")
            self.assertEqual(shared.base_tags(root), bases)
            self.assertEqual({p: package_kinds.plan(root, p, "runner", ["node", "python"], AMD64).tag for p in profiles}, profiles)
            self.assertNotEqual(variant_plan.plan(root, NAME, "runner", [], AMD64).tag, before)

    def test_a_change_to_the_profile_moves_the_variants_tag(self):
        with scratch() as tmp:
            root = context(tmp)
            before = variant_plan.plan(root, NAME, "runner", [], AMD64).tag
            shared.edit_profile(root, PROFILE, lambda d: d.update(about=d["about"] + " (edited)"))
            self.assertNotEqual(variant_plan.plan(root, NAME, "runner", [], AMD64).tag, before)


class TheRealPins(unittest.TestCase):
    def test_every_check_passes(self):
        variant_plan.check(ROOT, NAME, variant_plan.load(ROOT, NAME), AMD64)

    def test_every_requirement_has_exactly_one_hash(self):
        for name in ("cuda-toolkit.txt", "cuopt.txt", "highs-build.txt"):
            text = (FILES / name).read_text(encoding="utf-8")
            entries = re.findall(r"^(\S+==\S+) \\\n((?:    --hash=sha256:[0-9a-f]{64}(?: \\)?\n)+)", text, re.M)
            self.assertEqual(len(entries), len(pins(name)), name)
            for pin, hashes in entries:
                self.assertEqual(hashes.count("--hash="), 1, pin)

    def test_the_cuda_wheels_and_cuopt_are_one_closure_on_one_cuda_line(self):
        cuda, cuopt = pins("cuda-toolkit.txt"), pins("cuopt.txt")
        self.assertFalse(set(cuda) & set(cuopt))
        self.assertEqual(set(cuda), {"nvidia-cuda-nvcc", "nvidia-cuda-crt", "nvidia-nvvm", "nvidia-cuda-runtime",
                                     "nvidia-cublas", "nvidia-cusparse", "nvidia-cuda-cccl"})
        self.assertEqual(cuopt["cuopt-cu13"], "26.10.0")
        for name in ("nvidia-cuda-nvcc", "nvidia-cuda-crt", "nvidia-nvvm", "nvidia-cuda-runtime"):
            self.assertTrue(cuda[name].startswith("13.3."), name)
        for name in ("cuda-toolkit", "nvidia-cuda-nvrtc", "nvidia-nvjitlink", "cuda-bindings"):
            self.assertTrue(cuopt[name].startswith("13.3."), name)

    def test_the_venv_holds_what_the_profile_could_not(self):
        profile = variant_plan.requirement_names(
            (ROOT / "profiles" / PROFILE / "requirements.txt").read_text(encoding="utf-8"))
        cuopt = pins("cuopt.txt")
        self.assertEqual(profile["pandas"], "3.1.0")
        self.assertEqual(cuopt["pandas"], "3.0.6")
        self.assertNotIn("gurobipy", cuopt)

    def test_the_build_tools_are_not_in_the_profile(self):
        profile = variant_plan.requirement_names(
            (ROOT / "profiles" / PROFILE / "requirements.txt").read_text(encoding="utf-8"))
        self.assertFalse(set(pins("highs-build.txt")) & set(profile))

    def test_highspy_replaces_the_profiles_own_release(self):
        source = variant_plan.entries(variant_plan.load(ROOT, NAME), variant_plan.SOURCE)[0]
        profile = variant_plan.requirement_names(
            (ROOT / "profiles" / PROFILE / "requirements.txt").read_text(encoding="utf-8"))
        self.assertEqual(source["replaces"], f"highspy=={profile['highspy']}")
        self.assertIn(f"/v{profile['highspy']}/", source["url"])


class TheRefusals(unittest.TestCase):
    def refused(self, root: Path) -> str:
        err = io.StringIO()
        with mock.patch.object(variant_build.subprocess, "run", side_effect=AssertionError("Docker started")), \
                contextlib.redirect_stderr(err):
            code = variant_build.main(["--root", str(root), "--variant", NAME, "--image", "runner", "--base-digest", DIGEST])
        self.assertEqual(code, 2)
        return err.getvalue()

    def test_a_changed_requirements_file_is_refused_by_name(self):
        with scratch() as tmp:
            root = context(tmp)
            with (root / "variants" / NAME / "cuopt.txt").open("a", encoding="utf-8") as handle:
                handle.write("\n")
            self.assertIn("cuopt.txt has sha256", self.refused(root))

    def test_a_package_pinned_twice_is_refused(self):
        with scratch() as tmp:
            root = context(tmp)
            path = root / "variants" / NAME / "cuopt.txt"
            text = path.read_text(encoding="utf-8") + (FILES / "cuda-toolkit.txt").read_text(encoding="utf-8").split("\n", 3)[3]
            path.write_text(text, encoding="utf-8")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            edit_variant(root, lambda d: [e.update(sha256=digest) for e in d["adds"] if e["id"] == "cuopt"])
            self.assertIn("is pinned again", self.refused(root))

    def test_a_build_tool_that_is_not_an_exact_version_is_refused(self):
        with scratch() as tmp:
            root = context(tmp)
            edit_variant(root, lambda d: d["build_tools"]["packages"].append("gcc"))
            self.assertIn("'gcc' is not an exact", self.refused(root))

    def test_too_many_build_jobs_are_refused(self):
        with scratch() as tmp:
            root = context(tmp)
            edit_variant(root, lambda d: d.update(build_jobs=20))
            self.assertIn("build_jobs", self.refused(root))

    def test_a_build_needs_the_profile_images_digest(self):
        with scratch() as tmp:
            root = context(tmp)
            err = io.StringIO()
            with mock.patch.object(variant_build.subprocess, "run", side_effect=AssertionError("Docker started")), \
                    contextlib.redirect_stderr(err):
                code = variant_build.main(["--root", str(root), "--variant", NAME, "--image", "runner"])
            self.assertEqual(code, 2)
            self.assertIn("--base-digest", err.getvalue())

    def test_the_build_command_names_the_profile_by_tag_and_digest_and_carries_the_label(self):
        built = variant_plan.plan(ROOT, NAME, "runner", [], AMD64)
        command = variant_build.docker_command(ROOT, built, DIGEST, "optimization-gpu", "highs-check")
        self.assertIn(f"PROFILE_BASE={built.profile_tag}@{DIGEST}", command)
        self.assertIn("com.local.compose.project=optimization-gpu", command)
        self.assertEqual(command[command.index("--target") + 1], "highs-check")
        self.assertIn("--pull=false", command)


class TheEdits(unittest.TestCase):
    def tree(self, tmp: str, text: str) -> tuple[Path, list[dict]]:
        root = Path(tmp)
        (root / "a.txt").write_text(text, encoding="utf-8")
        before = hashlib.sha256(text.encode()).hexdigest()
        after = hashlib.sha256(text.replace("old", "new").encode()).hexdigest()
        return root, [{"file": "a.txt", "sha256": before, "after": after, "replace": [["old", "new"]]}]

    def test_the_pinned_edit_applies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, edits = self.tree(tmp, "keep old keep\n")
            self.assertEqual(edit_source.apply(edits, root), ["a.txt"])
            self.assertEqual((root / "a.txt").read_text(encoding="utf-8"), "keep new keep\n")

    def test_a_file_that_is_not_the_pinned_one_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, edits = self.tree(tmp, "keep old keep\n")
            (root / "a.txt").write_text("keep old keep!\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                edit_source.apply(edits, root)

    def test_a_text_that_occurs_twice_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, edits = self.tree(tmp, "old old\n")
            with self.assertRaises(SystemExit):
                edit_source.apply(edits, root)

    def test_the_real_edits_name_the_two_files_and_add_no_version_label(self):
        edits = json.loads((FILES / "highs-edits.json").read_text(encoding="utf-8"))["edits"]
        self.assertEqual([e["file"] for e in edits], ["cmake/python-highs.cmake", "highs/pdlp/cupdlp/cuda/CMakeLists.txt"])
        self.assertIn('"75;80;86;120"', edits[1]["replace"][0][1])


class TheRecipe(unittest.TestCase):
    TEXT = (ROOT / variant_plan.DOCKERFILE).read_text(encoding="utf-8")

    def test_the_dockerfile_passes_the_components_own_static_rules(self):
        self.assertEqual(runner_rules.dockerfile_findings(self.TEXT), [])
        self.assertIn("FROM ${PROFILE_BASE}", self.TEXT)

    def test_the_compiler_stays_in_the_build_stage(self):
        stages = re.findall(r"^FROM (\S+)(?: AS (\S+))?$", self.TEXT, re.M)
        self.assertEqual([ref for ref, name in stages if ref == "tools"], ["tools"])
        self.assertEqual(dict((name, ref) for ref, name in stages)["highs-build"], "tools")
        self.assertEqual(stages[-1], ("${PROFILE_BASE}", ""))
        self.assertNotIn("COPY --from=highs-build", self.TEXT)
        self.assertNotIn("COPY --from=tools", self.TEXT)

    def test_the_build_and_the_install_run_with_no_network(self):
        last = self.TEXT.split("\n# ------------------------------------ the variant\n")[1]
        build = self.TEXT.split("AS highs-build\n")[1].split("\nFROM ")[0]
        self.assertEqual(last.count("RUN "), last.count("RUN --network=none"))
        self.assertEqual(build.count("RUN "), build.count("RUN --network=none"))
        self.assertIn("RUN --network=none", build)

    def test_no_license_file_is_added(self):
        for path in [ROOT / variant_plan.DOCKERFILE, *(ROOT / variant_plan.RECIPE).glob("*.sh")]:
            self.assertNotRegex(path.read_text(encoding="utf-8").lower(), r"\.lic\b|grb_license")


def fake_docker(present: bool, probe_code: int = 0, probe_out: str = "GPU 0: Example GPU (UUID: GPU-0)\n",
                nvidia_on: tuple = (None,)):
    """A fake `docker`: `nvidia_on` lists the engines (None: the current context) whose info shows an nvidia runtime."""
    calls = []

    def run(command, **kwargs):
        host = (kwargs.get("env") or {}).get("DOCKER_HOST")
        if command[:2] == ["docker", "info"]:
            runtimes = '{"runc":{},"nvidia":{}}' if host in nvidia_on else '{"runc":{}}'
            return subprocess.CompletedProcess(command, 0, runtimes, "")
        calls.append((command, host) if host else command)
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 0 if present else 1, "sha256:" + "d" * 64 if present else "", "")
        if command[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(command, probe_code, probe_out if probe_code == 0 else "",
                                               "" if probe_code == 0 else "could not select device driver \"\" with capabilities: [[gpu]]")
        raise AssertionError(command)
    return run, calls


class TheChoice(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(variant.os.environ, {}, clear=False)
        patcher.start()
        variant.os.environ.pop(variant.HOST_ENV, None)
        variant.os.environ.pop("DOCKER_HOST", None)
        self.addCleanup(patcher.stop)

    def choose(self, mode, run, exists=lambda path: False):
        return variant.choose(ROOT, PROFILE, "runner", ["node", "python"], AMD64, mode, run=run, exists=exists)

    def test_with_no_gpu_on_the_current_context_the_local_socket_is_looked_up(self):
        run, calls = fake_docker(present=True, nvidia_on=(variant.NATIVE,))
        chosen = self.choose(None, run, exists=lambda path: path == "/var/run/docker.sock")
        self.assertEqual((chosen["variant"], chosen["docker_host"]), ("gpu", variant.NATIVE))
        self.assertTrue(all(host == variant.NATIVE for _, host in calls))

    def test_with_no_engine_that_has_the_runtime_the_cpu_image_runs_here(self):
        run, _ = fake_docker(present=False, nvidia_on=())
        chosen = self.choose(None, run)
        self.assertEqual((chosen["variant"], chosen["docker_host"]), ("cpu", None))
        self.assertIn("no engine lists an nvidia runtime", chosen["reason"])

    def test_the_gpu_engine_can_be_named(self):
        variant.os.environ[variant.HOST_ENV] = "unix:///example/gpu.sock"
        run, calls = fake_docker(present=True, nvidia_on=())
        chosen = self.choose(None, run)
        self.assertEqual(chosen["docker_host"], "unix:///example/gpu.sock")

    def test_without_the_gpu_image_the_cpu_image_runs_and_no_probe_starts(self):
        run, calls = fake_docker(present=False)
        chosen = self.choose(None, run)
        self.assertEqual((chosen["variant"], chosen["docker_args"]), ("cpu", []))
        self.assertEqual(chosen["image"], package_kinds.plan(ROOT, PROFILE, "runner", ["node", "python"], AMD64).tag)
        self.assertFalse([c for c in calls if c[:2] == ["docker", "run"]])

    def test_with_the_image_and_a_gpu_the_variant_runs_with_the_gpu(self):
        run, calls = fake_docker(present=True)
        chosen = self.choose("auto", run)
        self.assertEqual(chosen["variant"], "gpu")
        self.assertEqual(chosen["docker_args"], ["--gpus", "all"])
        self.assertEqual(chosen["image"], variant_plan.plan(ROOT, NAME, "runner", ["node", "python"], AMD64).tag)
        self.assertIsNone(chosen["docker_host"])
        self.assertNotIn("UUID", chosen["reason"])
        probe = [c for c in calls if c[:2] == ["docker", "run"]][0]
        self.assertEqual(probe[probe.index("--entrypoint") + 1], "nvidia-smi")
        self.assertIn("none", probe)

    def test_a_failed_probe_falls_back_with_no_error(self):
        run, _ = fake_docker(present=True, probe_code=125)
        chosen = self.choose(None, run)
        self.assertEqual(chosen["variant"], "cpu")
        self.assertIn("probe failed", chosen["reason"])

    def test_the_variable_forces_either_way(self):
        run, calls = fake_docker(present=True)
        self.assertEqual(self.choose("cpu", run)["variant"], "cpu")
        self.assertFalse(calls)
        for present, code in ((False, 0), (True, 125)):
            run, _ = fake_docker(present=present, probe_code=code)
            with self.assertRaises(variant.Refused):
                self.choose("gpu", run)
        with self.assertRaises(variant.Refused):
            self.choose("fastest", fake_docker(present=True)[0])

    def test_a_profile_with_no_variant_is_its_own_image(self):
        run, calls = fake_docker(present=True)
        chosen = variant.choose(ROOT, "claude-sdks", "runner", ["gradle", "java", "kotlin", "node", "python"], AMD64,
                                None, run=run)
        self.assertEqual(chosen["variant"], "cpu")
        self.assertFalse(calls)


class TheContract(unittest.TestCase):
    BLOCK = json.loads((ROOT / "consuming.json").read_text(encoding="utf-8"))["variant_choice"]

    def render(self, command, **slots):
        argv = [{"<profile>": PROFILE, "<runner|editor>": "runner", "<the declared set>": "node,python",
                 "<variant>": NAME}.get(one, one) for one in command]
        argv[argv.index("python3")] = sys.executable
        return argv

    def test_the_named_command_chooses_and_the_variable_is_the_modules_own(self):
        self.assertEqual(list(self.BLOCK["environment"]), [variant.ENV, variant.HOST_ENV])
        done = subprocess.run(self.render(self.BLOCK["chosen_by"]), cwd=ROOT, capture_output=True, text=True,
                              env={"PATH": "/usr/bin:/bin", variant.ENV: "cpu"})
        self.assertEqual(done.returncode, 0, done.stderr)
        chosen = json.loads(done.stdout)
        self.assertEqual((chosen["variant"], chosen["docker_args"]), ("cpu", []))

    def test_the_named_commands_list_both_images_and_print_the_variants_tag(self):
        done = subprocess.run(self.render(self.BLOCK["listed_by"]), cwd=ROOT, capture_output=True, text=True)
        listed = [json.loads(line) for line in done.stdout.splitlines()]
        self.assertEqual([one["variant"] for one in listed], ["cpu", "gpu"])
        done = subprocess.run(self.render(self.BLOCK["variant_tag_printed_by"]), cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(done.stdout.strip(), listed[1]["image"])
        self.assertIn("--gpus all", self.BLOCK["rule"])


if __name__ == "__main__":
    unittest.main()
