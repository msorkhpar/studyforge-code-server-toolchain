#!/bin/sh
# The offline proof of a built claude-sdks runner image, from the host. Run from the component root:
#   IMAGE=<the built tag> PRACTICE=/path/to/a/practice-folder \
#     /path/to/run-heavy.sh ccp-survey sh docs/measurements/claude-sdks-offline-proof.sh
# PRACTICE holds python/, typescript/, java/ and kotlin/ folders, each with starter/, reference/, tests/
# and at least one wrong-*/ solution (the course's practice layout). One container, --network none, a
# non-root user, a read-only root filesystem except a scratch tmpfs. Nothing but the practice (read-only)
# is mounted: no wheelhouse, no npm or Gradle cache comes from the host.
set -eu
: "${IMAGE:?set IMAGE to the profile image tag}"
: "${PRACTICE:?set PRACTICE to a practice folder}"
WRONG="${WRONG:-wrong-no-rollback}"
docker --context desktop-linux run --rm --network none --user 1000:1000 --read-only \
  --tmpfs /tmp:rw,size=3g -e HOME=/tmp/home -e GRADLE_USER_HOME=/tmp/gradle-home -e WRONG="$WRONG" \
  -v "$PRACTICE:/practice-src:ro" -v "$(pwd)/docs/measurements/claude-sdks:/measure:ro" --entrypoint sh "$IMAGE" -c '
set -eu
mkdir -p "$HOME" && cp -R /practice-src /tmp/practice && cd /tmp/practice
echo "GRADLE_RO_DEP_CACHE=$GRADLE_RO_DEP_CACHE npm_config_cache=${npm_config_cache:-}"
# verdict LABEL EXPECT COMMAND...: run, print the output tail, and require pass or an assertion failure
verdict() {
  label="$1"; expect="$2"; shift 2
  start=$(date +%s)
  if "$@" > /tmp/out.log 2>&1; then rc=0; else rc=$?; fi
  secs=$(( $(date +%s) - start ))
  if [ "$expect" = pass ]; then
    [ "$rc" = 0 ] || { tail -30 /tmp/out.log; echo "UNEXPECTED FAIL: $label"; exit 1; }
    echo "PASS    $label (${secs}s)"
  else
    [ "$rc" != 0 ] || { tail -30 /tmp/out.log; echo "UNEXPECTED PASS: $label"; exit 1; }
    grep -E "AssertionError|AssertionFailedError|assert |expected|not ok|FAILED" /tmp/out.log | head -4 | sed "s/^/        | /"
    grep -qE "AssertionError|AssertionFailedError|assert |expected:|not ok|FAILED" /tmp/out.log || { tail -30 /tmp/out.log; echo "FAILED WITHOUT AN ASSERTION: $label"; exit 1; }
    echo "FAIL ok $label (${secs}s)"
  fi
}
echo "== python (pytest)"
cd /tmp/practice/python
for s in reference starter "$WRONG"; do
  exp=fail; [ "$s" = reference ] && exp=pass
  verdict "python $s" $exp env SOLUTION_DIR="$PWD/$s" python3 -m pytest tests -q -p no:cacheprovider
done
echo "== typescript (node --test)"
cd /tmp/practice/typescript
for s in reference starter "$WRONG"; do
  exp=fail; [ "$s" = reference ] && exp=pass
  verdict "typescript $s" $exp env SOLUTION_DIR="$PWD/$s" node --test tests/conversation.test.ts
done
echo "== java (gradle)"
cd /tmp/practice/java
cat > settings.gradle.kts <<EOF
rootProject.name = "conversation"
EOF
cat > build.gradle.kts <<EOF
plugins { java }
val solution = (findProperty("solution") ?: "starter") as String
repositories { mavenCentral() }
java { toolchain { languageVersion = JavaLanguageVersion.of(25) } }
tasks.withType<JavaCompile> { options.release = 21 }
dependencies {
    testImplementation("org.junit.jupiter:junit-jupiter:5.10.2")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}
sourceSets {
    main { java.setSrcDirs(listOf(solution)) }
    test { java.setSrcDirs(listOf("tests")) }
}
layout.buildDirectory.set(file("../.build-java/\$solution"))
tasks.test {
    useJUnitPlatform()
    testLogging { events("passed", "failed"); showExceptions = true; exceptionFormat = org.gradle.api.tasks.testing.logging.TestExceptionFormat.SHORT }
}
EOF
for s in reference starter "$WRONG"; do
  exp=fail; [ "$s" = reference ] && exp=pass
  verdict "java $s" $exp gradle test --offline --no-daemon --console=plain -Psolution=$s -Porg.gradle.java.installations.auto-download=false
done
echo "== kotlin (gradle)"
cd /tmp/practice/kotlin
for s in reference starter "$WRONG"; do
  exp=fail; [ "$s" = reference ] && exp=pass
  verdict "kotlin $s" $exp gradle test --offline --no-daemon --console=plain -Psolution=$s -Porg.gradle.java.installations.auto-download=false
done
echo "== the SDKs, offline"
python3 - <<PY
import os, sysconfig
import anthropic, claude_agent_sdk, mcp, pydantic
print("python imports ok: anthropic, claude_agent_sdk, mcp, pydantic")
print("bundled binary present:", os.path.exists(os.path.join(sysconfig.get_paths()["purelib"], "claude_agent_sdk/_bundled/claude")))
PY
echo "== mcp server and client over stdio (python)"
cp /measure/*.py /tmp/ && python3 /tmp/mcp_client.py
echo "== read-only checks"
if touch /opt/profile/wheelhouse/x 2>/dev/null; then echo "WHEELHOUSE WRITABLE"; exit 1; else echo "wheelhouse is read-only"; fi
if touch /opt/profile/gradle-ro-cache/x 2>/dev/null; then echo "GRADLE CACHE WRITABLE"; exit 1; else echo "gradle cache is read-only"; fi
echo ALL OK
'
