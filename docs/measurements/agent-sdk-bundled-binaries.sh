#!/bin/sh
# Measure the Agent SDK's bundled Claude Code binaries. Run from the component root:
#   RUNNER=<a local runner image with python3, pip, node and npm> \
#   /path/to/run-heavy.sh ccp-survey sh docs/measurements/agent-sdk-bundled-binaries.sh
# Scratch lives in .work/agent-sdk-measure (gitignored, under the project, no host /tmp). Phase 1 is online
# (downloads); phase 2 runs with --network none.
set -eu
: "${RUNNER:?set RUNNER to a local image that has python3 and node}"
W="$(pwd)/.work/agent-sdk-measure"; rm -rf "$W"; mkdir -p "$W/home" "$W/proj"
cat > "$W/proj/package.json" <<'JSON'
{"name":"agent-sdk-measure","version":"1.0.0","private":true,"type":"module",
 "dependencies":{"@anthropic-ai/claude-agent-sdk":"0.3.287","zod":"4.6.5"},
 "devDependencies":{"typescript":"5.9.3"}}
JSON
D="docker --context desktop-linux run --rm --user 1000:1000 -e HOME=/work/home -v $W:/work -w /work --entrypoint sh"
echo "== online: python wheels (claude-agent-sdk==0.2.163)"
$D "$RUNNER" -c 'set -e; s=$(date +%s); python3 -m pip download -q --dest wheelhouse "claude-agent-sdk==0.2.163"; echo download_s=$(( $(date +%s)-s )); ls -l wheelhouse | grep -i claude; du -sh wheelhouse'
echo "== online: npm, default install and --omit=optional (lockfile from the default one)"
$D "$RUNNER" -c 'set -e; cd proj; s=$(date +%s); npm install --cache /work/cache --no-audit --no-fund >/dev/null 2>&1; echo npm_install_default_s=$(( $(date +%s)-s )); ls node_modules/@anthropic-ai; du -sh node_modules; du -sh node_modules/@anthropic-ai/claude-agent-sdk node_modules/@anthropic-ai/claude-agent-sdk-linux-x64* 2>&1'
echo "== offline: python with the binary, then with it removed"
$D --network none "$RUNNER" -c '
set -e
rm -rf site; s=$(date +%s); python3 -m pip install -q --no-index --find-links wheelhouse --target site claude-agent-sdk==0.2.163 2>&1 | tail -2
echo install_with_s=$(( $(date +%s)-s )); du -sh site
ls -l site/claude_agent_sdk/_bundled/
echo "-- hash check of the wheel (the pin is the wheel hash, unchanged by the removal)"; sha256sum wheelhouse/claude_agent_sdk-*.whl
PYTHONPATH=site python3 -c "import claude_agent_sdk; print(\"import with binary ok\", claude_agent_sdk.__version__ if hasattr(claude_agent_sdk,\"__version__\") else \"\")"
rm -f site/claude_agent_sdk/_bundled/claude; du -sh site
ls site/claude_agent_sdk/_bundled/ || true
PYTHONPATH=site python3 -c "
import claude_agent_sdk; print(\"import without binary ok\")
from claude_agent_sdk import ClaudeAgentOptions, query
print(\"names:\", ClaudeAgentOptions.__name__, query.__name__)"
echo "-- a query with no binary and no cli_path"
PY=$(command -v python3); PYTHONPATH=site PATH=/nonexistent "$PY" -c "
import asyncio
from claude_agent_sdk import query
async def go():
    async for m in query(prompt=\"hi\"): print(m)
try: asyncio.run(go())
except BaseException as e: print(type(e).__name__, str(e).splitlines()[0][:160])" 2>&1 | tail -2
'
echo "== offline: npm ci default vs --omit=optional, import, type check"
$D --network none "$RUNNER" -c '
set -e; cd proj
rm -rf node_modules; s=$(date +%s); npm ci --offline --cache /work/cache --no-audit --no-fund >/dev/null 2>&1; echo npm_ci_default_s=$(( $(date +%s)-s )); du -sh node_modules; ls node_modules/@anthropic-ai
rm -rf node_modules; s=$(date +%s); npm ci --offline --omit=optional --cache /work/cache --no-audit --no-fund >/dev/null 2>&1; echo npm_ci_omit_optional_s=$(( $(date +%s)-s )); du -sh node_modules; ls node_modules/@anthropic-ai
node -e "import(\"@anthropic-ai/claude-agent-sdk\").then(m=>console.log(\"import omit-optional ok\", typeof m.query))"
printf "import { query, type Options } from \"@anthropic-ai/claude-agent-sdk\";\nconst o: Options = {}; void query; void o;\n" > t.ts
node_modules/.bin/tsc --noEmit --module nodenext --moduleResolution nodenext --target es2022 --skipLibCheck t.ts && echo tsc_ok
'
