#!/bin/sh
# The offline proof of a built package profile image, from the host. Run from the component root:
#   IMAGE=<the built tag> NPM_DIR=profiles/<name>/<npm path> \
#     /path/to/run-heavy.sh ccp-survey sh docs/measurements/package-profile-offline-proof.sh
# One container, --network none, a non-root user, a read-only root filesystem except a scratch tmpfs.
# The project's package.json and lockfile are mounted read-only from the repository.
set -eu
: "${IMAGE:?set IMAGE to the profile image tag}"
: "${NPM_DIR:?set NPM_DIR to the npm entry directory}"
docker --context desktop-linux run --rm --network none --user 1000:1000 --read-only \
  --tmpfs /tmp:rw,size=512m -e HOME=/tmp/home -v "$(pwd)/$NPM_DIR:/proj-src:ro" --entrypoint sh "$IMAGE" -c '
set -eu
mkdir -p "$HOME"
echo "NODE_PATH=[${NODE_PATH:-}] npm_config_cache=[${npm_config_cache:-}]"
python3 - <<PY
import os, sysconfig
import claude_agent_sdk, mcp, pydantic
print("python imports ok: claude_agent_sdk, mcp, pydantic")
print("bundled binary present:", os.path.exists(os.path.join(sysconfig.get_paths()["purelib"], "claude_agent_sdk/_bundled/claude")))
PY
if touch /opt/profile/wheelhouse/x 2>/dev/null; then echo "WHEELHOUSE WRITABLE"; exit 1; else echo "wheelhouse is read-only"; fi
if python3 -m pip install --no-index --find-links /opt/profile/wheelhouse studyforge-absent-wheel >/dev/null 2>&1; then echo "ABSENT WHEEL INSTALLED"; exit 1; else echo "absent wheel refused"; fi
mkdir -p /tmp/proj && cp /proj-src/package.json /proj-src/package-lock.json /tmp/proj/ && cd /tmp/proj
npm ci --offline --ignore-scripts --omit=optional --no-audit --no-fund
ls node_modules/@anthropic-ai
node --input-type=module -e "const m = await import(\"@anthropic-ai/claude-agent-sdk\"); const z = await import(\"zod\"); console.log(\"node import ok:\", typeof m.query, typeof z.z)"
printf "import { query, type Options } from \"@anthropic-ai/claude-agent-sdk\";\nconst o: Options = {}; void query; void o;\n" > t.ts
node node_modules/typescript/bin/tsc --noEmit --module nodenext --moduleResolution nodenext --target es2022 --skipLibCheck t.ts && echo "tsc ok"
'
