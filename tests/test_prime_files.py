"""The prime digest covers what the build takes in: git-ignored files move no tag.

Run from the component root: `python3 -m unittest tests.test_prime_files -v`. No Docker.

Each case copies the fixture prime into a scratch folder as `prime/` and (where it matters) makes the
folder above it a git work tree with a `.gitignore`, as a course's prime sits in its repository.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "consuming"))
sys.path.insert(0, str(ROOT / "docker" / "editor"))

import builds  # noqa: E402
import prime_files  # noqa: E402

prime_contract = prime_files.prime_contract
FIXTURE = ROOT / "tests" / "fixtures" / "prime"
SET = ["gradle", "java", "maven"]
PLATFORM = "linux/amd64"
IGNORED = ("gradle/build/classes/Main.class", "gradle/.gradle/caches/x.bin", "maven/target/out.jar",
           "gradle/kotlin/build/tmp/a.txt")


def tag(prime: Path, image: str = "runner-prime") -> str:
    return builds.described(ROOT, image, SET, PLATFORM, prime)["tag"]


class PrimeFiles(unittest.TestCase):
    def setUp(self):
        # ⛔ Not under the component: its own `.gitignore` would ignore the copy.
        self.scratch = Path(tempfile.mkdtemp(prefix="prime-files-"))
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.prime = self.scratch / "prime"
        shutil.copytree(FIXTURE, self.prime)

    def tree(self, ignore: str = "build/\n.gradle/\ntarget/\n") -> None:
        (self.scratch / ".gitignore").write_text(ignore, encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.scratch)], check=True, stdin=subprocess.DEVNULL)

    def litter(self) -> None:
        for relative in IGNORED:
            path = self.prime / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"build output " + relative.encode())

    def test_a_clean_prime_keeps_the_digest_and_both_course_tags(self):
        before = tag(self.prime), tag(self.prime, "editor-prime"), prime_contract.read(self.prime).digest
        self.tree()
        self.assertEqual(prime_files.digest(self.prime), before[2])
        self.assertEqual((tag(self.prime), tag(self.prime, "editor-prime")), before[:2])
        self.assertIn("-prime-", before[0])

    def test_ignored_build_directories_do_not_move_the_tag(self):
        self.tree()
        clean = tag(self.prime), prime_files.digest(self.prime)
        self.litter()
        self.assertNotEqual(prime_contract.digest(self.prime), clean[1], "the plain digest does see them")
        self.assertEqual((tag(self.prime), prime_files.digest(self.prime)), clean)

    def test_a_real_change_moves_the_tag_tracked_or_not_yet_added(self):
        self.tree()
        self.litter()
        clean = tag(self.prime)
        pom = self.prime / "maven" / "pom.xml"
        pom.write_text(pom.read_text(encoding="utf-8") + "<!-- changed -->\n", encoding="utf-8")
        changed = tag(self.prime)
        self.assertNotEqual(changed, clean)
        (self.prime / "maven" / "src" / "main" / "java" / "prime" / "New.java").write_text("class New {}\n")
        self.assertNotEqual(tag(self.prime), changed)

    def test_the_staged_context_holds_the_digested_files_and_no_others(self):
        self.tree()
        self.litter()
        staged = prime_files.stage(self.prime, self.scratch / "context")
        self.assertEqual(staged, self.scratch / "context")
        self.assertEqual(sorted(p.relative_to(staged) for p in staged.rglob("*") if p.is_file()),
                         prime_files.files(self.prime))
        self.assertFalse([p for p in staged.rglob("*") if p.name in {"x.bin", "out.jar", "Main.class"}])
        self.assertEqual(prime_contract.digest(staged), prime_files.digest(self.prime))

    def test_nothing_ignored_means_the_prime_itself_is_the_context(self):
        self.tree()
        self.assertEqual(prime_files.stage(self.prime, self.scratch / "context"), self.prime)
        self.assertFalse((self.scratch / "context").exists())

    def test_outside_a_work_tree_every_file_counts_as_before(self):
        self.litter()
        self.assertEqual(prime_files.digest(self.prime), prime_contract.digest(self.prime))
        self.assertEqual(prime_files.stage(self.prime, self.scratch / "context"), self.prime)


if __name__ == "__main__":
    unittest.main()
