# The install stage's work (NO network). The wheelhouse and the npm cache arrive from the fetch
# stage under /opt/profile/fetched and are moved to their read-only homes.
set -eu
P=/opt/profile
NL='
'
mkdir -p "$P"
mv "$P/fetched/wheelhouse" "$P/wheelhouse"
mv "$P/fetched/requirements" "$P/requirements"
mv "$P/fetched/npm-cache" "$P/npm-cache"
rmdir "$P/fetched"
IFS="$NL"
for line in $PROFILE_WHEELS; do
  [ -n "$line" ] || continue
  IFS='|' read -r id req imports remove sdist <<ENTRY
$line
ENTRY
  echo "install: python-wheels $id"
  PIP_INDEX_URL=https://index.invalid/simple PIP_RETRIES=0 PIP_TIMEOUT=2 \
    python3 -m pip install --no-index --no-cache-dir --find-links "$P/wheelhouse" --require-hashes -r "$P/requirements/$id.txt" > /tmp/pip-install.log 2>&1 \
    || { cat /tmp/pip-install.log >&2; exit 1; }
  tail -n 3 /tmp/pip-install.log
  # ⭐ The proof that no index was consulted: the install is given an index that cannot exist, and
  # with `--no-index` pip never names it. Without the flag it would, and the build stops here.
  if grep -q "Looking in indexes" /tmp/pip-install.log; then
    echo "install: python-wheels $id: pip consulted a package index; the install must be --no-index" >&2; exit 1
  fi
  rm -f /tmp/pip-install.log
  site="$(python3 -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
  # ⭐ The omit flag: each declared file is deleted AFTER the hashed install, and a file that is
  # not there stops the build, so a wheel that no longer carries it is noticed.
  IFS=','
  for rel in $remove; do
    [ -n "$rel" ] || continue
    [ -f "$site/$rel" ] || { echo "install: python-wheels $id: remove_files names $rel, which the install does not hold" >&2; exit 1; }
    rm -f "$site/$rel"
    echo "install: removed $rel"
  done
  IFS="$NL"
  python3 -m pip check
  IFS=','
  for mod in $imports; do
    [ -n "$mod" ] || continue
    python3 -c "import $mod" || { echo "install: python-wheels $id: import $mod failed" >&2; exit 1; }
    echo "proof: import $mod"
  done
  IFS="$NL"
  # a wheel that is not in the wheelhouse is refused: the install cannot reach an index
  if python3 -m pip install --no-index --no-cache-dir --find-links "$P/wheelhouse" studyforge-absent-wheel >/dev/null 2>&1; then
    echo "install: python-wheels $id: a wheel outside the wheelhouse was installed" >&2; exit 1
  fi
  echo "proof: a wheel outside the wheelhouse is refused"
done
for line in $PROFILE_NPM; do
  [ -n "$line" ] || continue
  IFS='|' read -r id path omit imports <<ENTRY
$line
ENTRY
  flag=""
  [ "$omit" = "1" ] && flag="--omit=optional"
  echo "install: npm-packages $id"
  work="$(mktemp -d)"
  cp "/files/$path/package.json" "/files/$path/package-lock.json" "$work/"
  (
    cd "$work"
    npm_config_cache="$P/npm-cache" npm ci --offline --ignore-scripts --no-audit --no-fund $flag
    # `imports` (optional) names the specifiers proved instead of the dependencies' own names, for a
    # package whose bare name is not importable (its `exports` names a root file the package does not ship).
    names="$imports"
    if [ -z "$names" ]; then
      names="$(node -e 'const p=require("./package.json");console.log(Object.keys(p.dependencies||{}).join(" "))')"
    else
      names="$(echo "$names" | tr ',' ' ')"
    fi
    : > t.ts
    IFS=' '
    for dep in $names; do
      node --input-type=module -e "await import('$dep')" || { echo "install: npm-packages $id: import $dep failed" >&2; exit 1; }
      echo "proof: import $dep"
      printf 'import * as m%s from "%s";\nvoid m%s;\n' "$(echo "$dep" | tr -c 'a-zA-Z0-9\n' '_')" "$dep" "$(echo "$dep" | tr -c 'a-zA-Z0-9\n' '_')" >> t.ts
    done
    if [ -x node_modules/.bin/tsc ]; then
      node_modules/.bin/tsc --noEmit --module nodenext --moduleResolution nodenext --target es2022 --skipLibCheck t.ts
      echo "proof: tsc --noEmit type-checks a file against the packages' types"
    fi
  )
  rm -rf "$work"
done
rm -rf /root/.npm /root/.cache
chmod -R a+rX,a-w "$P/wheelhouse" "$P/requirements" "$P/npm-cache"
chmod a+rX,a-w "$P"
