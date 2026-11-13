# The OpenSpec proof, run at build time as the image's own user with NO network (see the profile's
# `npm-packages` entry `openspec`). A fresh project is initialised with no AI tool and validated strictly;
# HOME is a throwaway directory, so nothing is left in the image.
set -eu
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
export HOME="$work/home"
mkdir -p "$HOME" "$work/project"
cd "$work/project"
echo "proof: DO_NOT_TRACK=${DO_NOT_TRACK:-unset} OPENSPEC_TELEMETRY=${OPENSPEC_TELEMETRY:-unset}"
[ "${DO_NOT_TRACK:-}" = "1" ] && [ "${OPENSPEC_TELEMETRY:-}" = "0" ] || { echo "proof: telemetry is not off" >&2; exit 1; }
echo "proof: node --version: $(node --version)"
echo "proof: openspec --version: $(openspec --version)"
openspec init --tools none
test -f openspec/config.yaml || { echo "proof: openspec init wrote no openspec/config.yaml" >&2; exit 1; }
# `openspec validate --strict` with no item and no terminal only lists what it could validate, and exits 1;
# `--all` validates every change and spec, which is what a non-interactive run means.
openspec validate --all --strict
openspec list
echo "proof: openspec init and validate --all --strict pass as $(id -u)"
