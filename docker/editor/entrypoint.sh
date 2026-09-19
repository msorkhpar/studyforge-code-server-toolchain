#!/bin/sh
# The editor's entrypoint: seed the reader's settings once, then hand over to
# the base image's own entrypoint with the arguments untouched.
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
set -eu

SEED_SETTINGS=/opt/code-server/seed/settings.json

log() { printf '[editor-entrypoint] %s\n' "$*"; }

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
