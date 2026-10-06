# Handback: release/claude-cert-support into main

- Merge commit `d9d3227` (`--no-ff`, parents origin/main `06a7354` and release `4001e4f`); `docs/cloud/` removed in `9e52c31`.
- Conflicts: none. main had not moved since the release branch left it, so the merged tree equals the release tree; pins, editor-pins, consuming and profiles (every sha256 included) are the release's, and only release commits move a version.
- Tests: `python3 -m unittest discover -s tests` (one process). 606 run, 114 skipped (need Docker; no daemon here), 4 failed. origin/main alone: OK. The release branch alone failed the same 70 as the merge.
- Fixed in `6b9cb30` (stale literals on the release branch, not merge damage): editor inputs digest `dfccda94afd6` -> `b32ceaf453ce`, the 2 primed editor tags, the 4 profile editor tags, and the `kotlin-ls` check a kotlin set now carries.
- Not fixed, 4 subtests: `test_profile_extension.TheSeedBlock.test_the_editors_own_seed_and_recipe_know_no_server_and_no_setting` asserts the editor (Dockerfile, editor_plan.py, entrypoint.sh, editor-pins.json) never names the Kotlin server. That is a design rule from W544 (the server rides the kotlin-editor profile). Commits 117eaa0 and 8ddd7d1 bake the server into the editor on purpose, so the two designs conflict. Decide which one stays, and whether a profile seed and the editor's Machine settings may both set `kotlin.languageServer.path`.

Tags (`--print-tag`, linux/amd64, default set; editor arm64 suffix matches):

| image | origin/main | release | merge |
|---|---|---|---|
| runner (minimal) | none-f8f1db0be48a | same | same |
| editor | gradle-java-kotlin-node-python-14e3f747ce03 | ...-b32ceaf453ce | ...-b32ceaf453ce |
| claude-sdks runner / editor | (no profiles) | 2ed9b7f2bc32 / 4e1eae568548 | same |
| fixture-libs runner / editor | - | a4519ad7340e / 6c76680223b7 | same |
| fixture-packages runner / editor | - | 05b81b597597 / 0b8f49ccb0dd | same |
| jvm-frameworks runner / editor | - | e0de42be2689 / 56185b2d903b | same |
| kotlin-editor editor | - | 134c22d78b7b | same |

- Rebuild: only images not already built from the release head. The runner tag has not moved since main. Every editor and profile tag on main moves, which the release changes explain.
- Attribution: the brief asked for a `Claude Sonnet 5.5` co-author line. These commits name the model that actually wrote them.
