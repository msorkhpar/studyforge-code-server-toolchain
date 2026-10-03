# The Agent SDK's bundled Claude Code binaries

Measured with `docs/measurements/agent-sdk-bundled-binaries.sh` (one container, a local runner image
with Python 3.14.7, Node 24.21.0, npm 11.19.0; online phase for downloads, `--network none` for
every install and import). Versions: `claude-agent-sdk` 0.2.163 (Python), `@anthropic-ai/claude-agent-sdk`
0.3.287, `zod` 4.6.5, `typescript` 5.9.3. Figures are one run on linux/amd64.

| reading | with the binary | without |
|---|---|---|
| Python wheel file (`pip download`) | 103 MB (the wheel is one artifact; its hash is the pin) | n/a: the binary cannot be left out of the download |
| Python install (`pip install --no-index --target`) | 284 MB, 5 s | 54 MB after deleting `claude_agent_sdk/_bundled/claude` (241.7 MB file) |
| npm `node_modules` (`npm ci --offline`) | 311 MB, 5 s; `claude-agent-sdk-linux-x64` is 234 MB, the SDK 5.3 MB | 78 MB, 3 s with `--omit=optional`; the platform package is not installed |

Findings.

1. **Python.** Deleting the one file `_bundled/claude` after the hashed install leaves the SDK
   importable offline (`import claude_agent_sdk`, `ClaudeAgentOptions`, `query` all load). A
   `query(...)` with no binary, no `cli_path` and no `claude` on `PATH` raises the SDK's own
   `CLINotFoundError` ("Claude Code not found. Install with: ..."). The wheel's hash is untouched, since
   the removal happens after the verified install, so the pin stays the wheel hash. The recipe step
   (the `python-wheels` kind) must delete exactly that file, deterministically, and fail if it is absent.
2. **npm.** `npm ci --omit=optional` skips the per-platform binary package, the SDK's
   `import` resolves (`query` is a function), and `tsc --noEmit` against the SDK types passes.
   The lockfile still lists the optional package, so the pin set is the same; only the install flag
   differs (`omit_optional: true` on the `npm-packages` kind).
3. **Graded runner.** The tag of the profile folds the profile file and recipe, not the installed
   bytes, so the binaries' presence never enters it; omitting them makes the profile smaller by
   about 232 MB (Python) plus 234 MB (npm) at install, and about 103 MB of the downloaded Python wheel
   stays in the pinned input but is not kept in the image.
4. **Route for a live Agent SDK example.** No `claude-sdks-live` profile is built; a live example
   states that it needs the reader's own install. Measured basis if that is ever revisited: a second profile layered on `claude-sdks` would hold
   the Python binary (241.7 MB, obtainable only by the full 103 MB wheel, whose hash is already a
   pin) and the npm platform package (234 MB), pinned as two entries; it would be used only by live runs.
   The `claude --version` offline check of the survey (2.1.286) shows the binary starts without a model
   call.

What this row did not build: the recipe step and the `omit_optional` flag are the entry kinds of
the `python-wheels` and `npm-packages` kinds; the stub profile declares them (`remove_bundled_binary`, `omit_optional`) so the intent
is on file, and the measurements above are the evidence those rows implement against.
