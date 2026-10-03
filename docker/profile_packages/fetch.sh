# The fetch stage's work (network on). Reads PROFILE_WHEELS and PROFILE_NPM, one entry per line:
#   wheels: id|requirements|imports|remove_files|allow_sdist
#   npm:    id|path|omit_optional
set -eu
mkdir -p /fetched/wheelhouse /fetched/requirements /fetched/npm-cache
NL='
'
IFS="$NL"
for line in $PROFILE_WHEELS; do
  [ -n "$line" ] || continue
  IFS='|' read -r id req imports remove sdist <<ENTRY
$line
ENTRY
  only="--only-binary=:all:"
  [ "$sdist" = "1" ] && only=""
  echo "fetch: python-wheels $id from $req"
  python3 -m pip download --no-cache-dir --require-hashes $only --dest /fetched/wheelhouse -r "/files/$req" \
    || { echo "fetch: python-wheels $id: a wheel is missing, wrong, or only a source distribution (set allow_sdist with a reason to build one)" >&2; exit 1; }
  cp "/files/$req" "/fetched/requirements/$id.txt"
done
for line in $PROFILE_NPM; do
  [ -n "$line" ] || continue
  IFS='|' read -r id path omit <<ENTRY
$line
ENTRY
  flag=""
  [ "$omit" = "1" ] && flag="--omit=optional"
  echo "fetch: npm-packages $id from $path"
  work="$(mktemp -d)"
  cp "/files/$path/package.json" "/files/$path/package-lock.json" "$work/"
  (cd "$work" && npm ci --ignore-scripts --no-audit --no-fund --cache /fetched/npm-cache $flag) \
    || { echo "fetch: npm-packages $id: npm ci refused the lockfile" >&2; exit 1; }
  rm -rf "$work"
done
rm -rf /root/.npm /root/.cache
