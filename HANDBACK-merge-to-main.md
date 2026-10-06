# Handback: release/claude-cert-support into main

- Merge: `--no-ff` of the release head into origin/main; `docs/cloud/` removed after it. No conflicts: main had not moved since the release left it, so the merged tree equals the release tree and only release commits move a version.
- Fixed earlier on this branch (stale literals from the release, not merge damage): the editor inputs digest, the 2 primed editor tags, the 4 profile editor tags, and the `kotlin-ls` check a kotlin set now carries.
- Rewritten: `TheSeedBlock.test_the_editors_own_seed_and_recipe_know_no_server_and_no_setting` is now `test_the_editors_own_seed_names_the_baked_server_and_no_profile_seed_points_elsewhere`. It asserts the editor's Machine settings seed names exactly `/opt/code-server/kotlin-ls/bin/kotlin-language-server`, the recipe installs `kls-classpath` to `/opt/code-server/seed/` and the entrypoint writes it on every start, every `kotlin.languageServer.path` under `docker/editor` is that path, and no editor profile's seed sets it to another value. Kept: the reader's seeds (`seed/*.json`) and `pins.json` name no server.
- ⚠️ That test FAILS, on real data: `profiles/kotlin-editor.json` still seeds `kotlin.languageServer.path` = `/opt/profile/editor-extensions/kotlin-language-server/server/bin/kotlin-language-server`. That seed lands in the reader's User settings while the baked path is in Machine settings, so a kotlin-editor image carries two servers and two answers for one setting. Not changed here: the profile, and the other tests that pin its path (`SERVER`, the seed-block tests), are the old design. Decide whether to drop the server, JDK and patches from that profile or to drop the setting from its seed.
- Tests (`python3 -m unittest discover -s tests`, one process, no Docker): 606 run, 114 skipped (need Docker), 1 failed (the one above). This rewrite of the handback also clears `test_no_citations`, which the previous handback tripped with commit hashes.

Tags (`--print-tag`, linux/amd64, default set; editor arm64 suffix matches):

| image | origin/main | release = merge |
|---|---|---|
| runner (minimal) | `none-f8f1db0be48a` | same |
| editor | `...-14e3f747ce03` | `...-b32ceaf453ce` |
| claude-sdks runner / editor | (no profiles) | `...-2ed9b7f2bc32` / `...-4e1eae568548` |
| fixture-libs runner / editor | - | `...-a4519ad7340e` / `...-6c76680223b7` |
| fixture-packages runner / editor | - | `...-05b81b597597` / `...-0b8f49ccb0dd` |
| jvm-frameworks runner / editor | - | `...-e0de42be2689` / `...-56185b2d903b` |
| kotlin-editor editor | - | `...-134c22d78b7b` |

- Rebuild only images not already built from the release head; the runner tag has not moved since main.
- Attribution: commits name the model that actually wrote them.
