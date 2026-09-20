#!/bin/sh
# The editor's entrypoint: seed the reader's settings and the prime's caches
# once, then hand over to the base image's own entrypoint with the arguments
# untouched.
#
# The prime's caches (TC-03) are built into the image under
# /opt/code-server/prime and copied to where the tools look — the Gradle user
# home and the Maven local repository — only when that directory is EMPTY, so
# a volume that already holds a reader's cache is never touched. The copy goes
# through a .seed-partial sub-directory, so a container killed mid-copy leaves
# the directory "still empty" and the next start finishes the job. The copy
# is owned by the running uid; the seed in the image is root's.
#
# The user data directory lives on a named volume, so anything placed there at
# image-build time is invisible once the volume is mounted, and a volume from an
# earlier image may already hold the reader's edits. So the seed is written
# ONLY when no settings file exists, and never overwrites: an overwrite would
# lose the reader's edits on every start.
#
# ⛔ The final `exec` chains to /usr/bin/entrypoint.sh, never to code-server
# directly: bypassing it loses the base's fixuid, DOCKER_USER handling and
# dumb-init. ⛔ There is no mode that runs some other command instead of
# code-server: the reader's code runs in the runner image (TC-01/6).
#
# ⛔ fixuid RUNS FIRST, and that ordering belongs to the compose contract
# (TC-05). The base runs it too, in /usr/bin/entrypoint.sh — which is AFTER
# everything below. A consumer runs this container as the uid:gid that owns its
# sources, and any uid but the image's own has no passwd entry until fixuid
# writes one: HOME is then `/`, the seed below tries `//.local` and fails, and
# the container exits before code-server starts. So it runs here as well. It is
# the same command, it is idempotent, and both halves are measured in
# tests/test_consuming_image.py.
set -eu

eval "$(fixuid -q)"

SEED_SETTINGS=/opt/code-server/seed/settings.json
SEED_GRADLE=/opt/code-server/prime/gradle-home
SEED_MAVEN=/opt/code-server/prime/maven-repo

log() { printf '[editor-entrypoint] %s\n' "$*"; }

# seed_tree SEED TARGET LABEL
seed_tree() {
    if [ ! -d "$1" ]; then
        log "no $3 seed in this image; skipping"
        return
    fi
    mkdir -p "$2"
    # Anything other than a leftover partial copy counts as "not empty".
    if [ -n "$(ls -A "$2" | grep -vx '.seed-partial' || true)" ]; then
        log "$3 at $2 is not empty; leaving it alone"
        return
    fi
    log "seeding $3 at $2"
    rm -rf "$2/.seed-partial"
    cp -R --preserve=mode,timestamps "$1" "$2/.seed-partial"
    find "$2/.seed-partial" -mindepth 1 -maxdepth 1 -exec mv -t "$2" -- {} +
    rmdir "$2/.seed-partial"
    log "$3 seeded"
}

seed_tree "$SEED_GRADLE" "${GRADLE_USER_HOME:-${HOME:-/home/coder}/.gradle}" "gradle home"
seed_tree "$SEED_MAVEN" "${HOME:-/home/coder}/.m2/repository" "maven repository"

# code-server's default, unless --user-data-dir was passed on the command line.
user_data_dir="${HOME:-/home/coder}/.local/share/code-server"
prev=""
for arg in "$@"; do
    case "$arg" in
        --user-data-dir=*) user_data_dir="${arg#--user-data-dir=}" ;;
        *) [ "$prev" = "--user-data-dir" ] && user_data_dir="$arg" ;;
    esac
    prev="$arg"
done

target="$user_data_dir/User/settings.json"
if [ -e "$target" ]; then
    log "settings exist at $target; leaving them alone"
else
    log "writing default settings to $target"
    mkdir -p "$user_data_dir/User"
    cp "$SEED_SETTINGS" "$target"
fi

exec /usr/bin/entrypoint.sh "$@"
