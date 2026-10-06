# Brief: bring release/claude-cert-support into main

For a cloud session working alone on this repository. Push only the branch `cloud/merge-to-main`.
Budget cap: about 15 USD; stop and hand back what you have when you near it. No Docker is
available; tests that build or run images skip or are left out, and are reported as such.

## Goal

`release/claude-cert-support` holds the toolchain changes a new course needed: Python and
TypeScript runtimes and profiles, the Claude SDK profile, the Kotlin language server baked into
the editor (with its own classpath script, so a newer Kotlin runtime no longer marks every file
as an error), and the runner changes that go with them. The images built from it have served a
course and an existing course has been rebuilt on it and checked by hand. Bring it into `main`:

1. Branch `cloud/merge-to-main` from `origin/main`. Merge `origin/release/claude-cert-support`
   into it with a merge commit (no squash, no rebase).
2. Resolve conflicts keeping both sides' intent. Pins (`pins.json`, `editor-pins.json`,
   `consuming.json`, profiles) must stay consistent: every pinned file keeps its sha256, and no
   version moves that neither side moved.
3. Remove the folder `docs/cloud/` (working notes, including this brief) in a separate commit
   after the merge.
4. Run every test that needs no Docker, with at most 4 workers. Fix what the merge broke. A
   failure that also fails on `origin/main` alone, or that needs Docker, is reported, not fixed.

## Rules

- No personal data, keys or machine paths in any file.
- Image tags are derived from build inputs; a tag that moves is expected only where an input
  changed. List the tags (`--print-tag` of each build script) on `origin/main`, the release branch
  and the merge, so the maintainer can see which images must be rebuilt.
- Commit messages end with the line
  `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Push only `cloud/merge-to-main`.
  No pull request.

## Hand back

Commit `HANDBACK-merge-to-main.md` at the repository root of the branch, at most 25 lines: the
merge commit, the conflicts and how each was resolved, the test numbers with each failure's
reason, the tag table, and anything left for the maintainer.
