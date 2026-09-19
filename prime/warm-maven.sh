#!/bin/sh
# The MAVEN warmer (TC-03): run a consumer's prime project's `test` phase once,
# so a local repository holds everything a first `mvn -o test` needs.
#
#   warm-maven.sh warm  PROJECT REPO   run `mvn test` with the network into REPO
#   warm-maven.sh prove PROJECT REPO   run a fresh copy OFFLINE against a copy of REPO
#   warm-maven.sh check LOG            only the source check, on a `mvn -B` log
#
# ⭐ Maven resolves every dependency a POM DECLARES for every module, used or
# not, so running the phase warms what the POM declares, not what the tests
# reference. ⭐ Every file is checked against Maven Central's own checksum as
# it arrives (`-C`, strict checksums), and the request carries a placeholder
# User-Agent and no identity.
#
# ⛔ THE SOURCES MUST BE REAL: a module that compiles no sources, or runs no
# tests, never resolves what those steps need, so the build fails naming it.
# There is no Maven wrapper to honour: the image's pinned Maven IS the version
# (the version guards refuse a prime whose wrapper names another).
set -eu

AGENT="Example/0.1 (+https://example.invalid)"

fail() { printf 'prime: %s\n' "$*" >&2; exit 1; }

check() {
    awk '
    /^\[INFO\] --- .* @ [^ ]+ ---$/ { module = $(NF - 1); goal = $3; sub(/.*:/, "", goal) }
    /^\[INFO\] No sources to compile$/ {
        printf "prime: maven module %s compiles no sources in %s: a step with no sources never resolves what it needs, so the prime would prime nothing; give it one real source and one real test\n", module, goal > "/dev/stderr"
        bad = 1
    }
    /^\[INFO\] No tests to run\.$/ || /^\[INFO\] Tests are skipped\.$/ {
        printf "prime: maven module %s runs no tests: the test step never resolves its provider, so the prime would prime nothing; give it one real test\n", module > "/dev/stderr"
        bad = 1
    }
    /^\[INFO\] Tests run: [1-9]/ { tested = 1 }
    END {
        if (!bad && !tested) {
            print "prime: the maven prime ran no test: a prime with no sources primes nothing" > "/dev/stderr"
            bad = 1
        }
        exit bad
    }' "$1"
}

build() {  # PROJECT REPO [-o]
    work="$(mktemp -d)"
    cp -R "$1"/. "$work"/
    log="$(mktemp)"
    repo="$2"
    shift 2
    if ! (cd "$work" && mvn -B -C -ntp "$@" -Dmaven.repo.local="$repo" \
            "-Daether.connector.userAgent=$AGENT" test) > "$log" 2>&1; then
        tail -n 60 "$log" >&2
        fail "the maven prime did not build"
    fi
    check "$log"
    rm -rf "$work" "$log"
}

mode="${1:-}"
case "$mode" in
    check)
        [ $# -eq 2 ] || fail "usage: warm-maven.sh check LOG"
        check "$2" ;;
    warm)
        [ $# -eq 3 ] || fail "usage: warm-maven.sh warm PROJECT REPO"
        mkdir -p "$3"
        build "$2" "$3"
        # Download bookkeeping names the host a file came from and when; an
        # offline build needs none of it, and it would differ build to build.
        find "$3" \( -name '_remote.repositories' -o -name '*.lastUpdated' \
            -o -name 'resolver-status.properties' \) -delete
        chmod -R a+rX "$3"
        echo "prime: maven repository at $3" ;;
    prove)
        [ $# -eq 3 ] || fail "usage: warm-maven.sh prove PROJECT REPO"
        repo="$(mktemp -d)"
        cp -R "$3"/. "$repo"/
        build "$2" "$repo" -o
        rm -rf "$repo"
        echo "prime: a fresh copy of the maven prime runs its tests offline from the repository" ;;
    *)
        fail "usage: warm-maven.sh warm|prove PROJECT REPO | check LOG" ;;
esac
