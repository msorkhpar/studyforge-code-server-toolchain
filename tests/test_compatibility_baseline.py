"""The computed tags of every runtime set this component publishes or a lock names, recorded.

Run from the component root: `python3 -m unittest tests.test_compatibility_baseline -v`.

⭐ **What is held.** An image's tag is a function of its inputs, and a consumer pins
that tag (or a digest published under it). So a tag that moves orphans every base
already published under the old one. This file records, as literals, the tag
`--print-tag` computes for each runtime set below, on both images, both
architectures, unprimed and primed, and fails if any of them moves. The literals
are NOT derived from the code at run time: a test that recomputed its own
expectation could not fail.

⭐ **Why the set may not change the digest of another set.** The suffix after the
architecture is the digest of the build's inputs. It is the same for every
runtime set today, which is exactly why a new pin that enters those inputs for
every set moves every tag. A runtime's pin enters a set's inputs only when the set
names that runtime.

⭐ **How the literals were produced.** From the unmodified code of this
checkout, by running the command each test names (`--print-tag` with that
`--runtimes`, `--platform` and, for a primed tag, `--prime tests/fixtures/prime`
or a copy of one of its projects):

    python3 docker/minimal/build.py --runtimes java,maven --platform linux/amd64 --print-tag
    python3 docker/editor/build.py  --runtimes java,maven --platform linux/amd64 --print-tag

⛔ Regenerate a literal ONLY on purpose, in a change that says why a published tag
is allowed to move. A primed tag also reads the fixture projects, so editing a
fixture project moves it, and that is a deliberate act too.

Standard library only; no Docker.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "prime"
SCRIPT = {"runner": ROOT / "docker" / "minimal" / "build.py", "editor": ROOT / "docker" / "editor" / "build.py"}
REPOSITORY = {"runner": "code-server-toolchain/runner", "editor": "code-server-toolchain/editor"}
#: The digest of each image's build inputs, the suffix every unprimed tag ends with.
DIGEST = {"runner": "f8f1db0be48a", "editor": "14e3f747ce03"}

SETS = {
    "java": "java",
    "java,maven": "java-maven",
    "java,maven,node,python": "java-maven-node-python",
    "gradle,java,kotlin,node,python": "gradle-java-kotlin-node-python",
    "": "none",
}
ARCH = {"linux/amd64": "amd64", "linux/arm64": "arm64"}

#: (image, declared set, prime projects kept, expected tag after the repository).
PRIMED = (
    ("runner", "java,maven", ("maven",), "java-maven-amd64-fb008dba19a8"),
    ("editor", "java,maven", ("maven",), "java-maven-amd64-bb80c9181b25"),
    ("runner", "gradle,java,maven", ("gradle", "maven"), "gradle-java-maven-amd64-1d07cdf617ac"),
    ("editor", "gradle,java,maven", ("gradle", "maven"), "gradle-java-maven-amd64-63b121508d75"),
)


def print_tag(image: str, runtimes: str | None, platform: str, prime: Path | None = None) -> str:
    command = [sys.executable, str(SCRIPT[image]), "--platform", platform, "--print-tag"]
    if runtimes is not None:
        command += ["--runtimes", runtimes]
    if prime is not None:
        command += ["--prime", str(prime)]
    done = subprocess.run(command, capture_output=True, text=True, stdin=subprocess.DEVNULL, check=False)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


class TheUnprimedTags(unittest.TestCase):
    def test_every_recorded_set_keeps_its_tag_on_both_images_and_both_architectures(self):
        for image in SCRIPT:
            for runtimes, name in SETS.items():
                for platform, arch in ARCH.items():
                    with self.subTest(image=image, runtimes=runtimes or "(none)", platform=platform):
                        expected = f"{REPOSITORY[image]}:{name}-{arch}-{DIGEST[image]}"
                        self.assertEqual(print_tag(image, runtimes, platform), expected)

    def test_the_default_sets_keep_their_tags(self):
        """The runner declares nothing by default; the editor's default is its own recorded set."""
        self.assertEqual(print_tag("runner", None, "linux/amd64"),
                         f"{REPOSITORY['runner']}:none-amd64-{DIGEST['runner']}")
        self.assertEqual(print_tag("editor", None, "linux/amd64"),
                         f"{REPOSITORY['editor']}:gradle-java-kotlin-node-python-amd64-{DIGEST['editor']}")

    def test_the_inputs_digest_is_the_same_for_every_set_so_a_set_names_only_itself(self):
        """The digest suffix does not depend on the set: no set's inputs carry another set's pin."""
        for image in SCRIPT:
            suffixes = {print_tag(image, runtimes, "linux/amd64").rsplit("-", 1)[1] for runtimes in SETS}
            self.assertEqual(suffixes, {DIGEST[image]})


class ThePrimedTags(unittest.TestCase):
    def test_every_recorded_primed_tag_is_unchanged(self):
        for image, runtimes, keep, expected in PRIMED:
            with self.subTest(image=image, runtimes=runtimes, prime=keep):
                scratch = Path(tempfile.mkdtemp())
                try:
                    prime = scratch / "prime"
                    for project in keep:
                        shutil.copytree(FIXTURE / project, prime / project)
                    self.assertEqual(print_tag(image, runtimes, "linux/amd64", prime),
                                     f"{REPOSITORY[image]}:{expected}")
                finally:
                    shutil.rmtree(scratch, ignore_errors=True)

    def test_a_primed_tag_is_not_an_unprimed_one(self):
        for image, runtimes, _keep, expected in PRIMED:
            self.assertNotIn(DIGEST[image], expected)


if __name__ == "__main__":
    unittest.main()
