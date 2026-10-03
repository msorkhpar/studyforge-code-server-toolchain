# The install stage's work (NO network). The wheelhouse and the npm cache arrive from the fetch
# stage under /opt/profile/fetched and are moved to their read-only homes.
set -eu
P=/opt/profile
NL='
'
mkdir -p "$P"
# ⭐ The editor's extensions (`editor-extension` entries with `install: vsix`): each archive was fetched and
# checked against its pin, and is installed here with NO network into the extensions directory the editor
# reads, the way the base installed its own. The install is proved by the extension's own id and version in
# `--list-extensions`. The entry's settings go into the settings seed, as one block, and only where it exists.
IFS_BEFORE="$IFS"
for line in $PROFILE_VSIX; do
  [ -n "$line" ] || continue
  IFS='|' read -r id url sha provides <<ENTRY
$line
ENTRY
  echo "install: editor-extension $id"
  code-server --extensions-dir /opt/code-server/extensions --install-extension "$P/fetched/vsix/$id.vsix" > /tmp/vsix-install.log 2>&1 \
    || { cat /tmp/vsix-install.log >&2; echo "install: editor-extension $id: the archive did not install" >&2; exit 1; }
  rm -f /tmp/vsix-install.log
  code-server --extensions-dir /opt/code-server/extensions --list-extensions --show-versions 2>/dev/null | grep -qx "$provides" \
    || { echo "install: editor-extension $id: --list-extensions does not show $provides" >&2; exit 1; }
  echo "proof: $provides is installed"
done
if [ -n "$PROFILE_VSIX" ]; then
  if [ -n "$PROFILE_VSIX_SEED" ]; then
    seed=/opt/code-server/seed/settings.json
    test -f "$seed" || { echo "install: the editor has no settings seed at $seed" >&2; exit 1; }
    printf '%s\n' "$PROFILE_VSIX_SEED" > /tmp/vsix-seed-block
    sed -i '/^{$/r /tmp/vsix-seed-block' "$seed"
    rm -f /tmp/vsix-seed-block
    grep -q '@runtime kotlin' "$seed" || { echo "install: the settings block did not land in $seed" >&2; exit 1; }
  fi
  rm -rf /root/.local/share/code-server /root/.config/code-server
  chown -R 1000:1000 /opt/code-server/extensions
  chmod -R a+rX /opt/code-server/extensions
fi
rm -rf "$P/fetched/vsix"
IFS="$IFS_BEFORE"
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
