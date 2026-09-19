# check=skip=InvalidDefaultArgInFrom
# ⭐ That directive is deliberate: the linter warns that an ARG used in FROM has
# no default, and having NO default is the point (see below).
#
# The EDITOR image (TC-01): code-server, with the runner's pinned toolchains and
# pinned extensions, and a shell that finds every toolchain.
#
# ⛔ Build it ONLY through `docker/editor/build.py`, from the component root:
#     python3 docker/editor/build.py
# It builds the runner for the same set first, then this file. Every ARG below
# is passed from `pins.json` / `editor-pins.json` and carries NO default, so a
# build that bypasses them fails on an empty argument instead of choosing.
#
# ⛔ This file chooses NO runtime version. Every runtime is COPIED out of the
# runner image (`docker/minimal/`) built for the same set, so `pins.json` stays
# the one place a runtime version is chosen (register ruling, PO round 122).
# ⛔ No stage here is `FROM scratch` (W374/3): a bare scratch stage was served
# from another stage's cache and put every runtime in a `python` runner.
# ⛔ No Docker socket, no `docker` CLI. The reader's code runs in the RUNNER,
# never here: the extraction source's `exec` mode is dropped (TC-01/6).

ARG RUNNER_IMAGE
ARG EDITOR_BASE
ARG FETCH_IMAGE

# ------------------------------------------------------------------- toolchain
FROM ${RUNNER_IMAGE} AS toolchain

# ----------------------------------------------------------------------- fetch
# Every extension and the TypeScript tarball, each checked against the sha256
# RECORDED in editor-pins.json. No checksum is fetched: a host that serves a
# different file fails the build here, naming it.
FROM ${FETCH_IMAGE} AS fetch
ARG FETCH
COPY docker/editor/fetch.py /fetch.py
RUN printf '%s\n' "${FETCH}" > /tmp/fetch.txt \
 && python3 /fetch.py /tmp/fetch.txt /fetch \
 && rm /tmp/fetch.txt

# ---------------------------------------------------------------------- editor
FROM ${EDITOR_BASE} AS editor
USER root

# The runtimes, exactly as the runner holds them: /opt is the declared set's
# trees and nothing else (W374), and /usr/local carries the pinned Python with
# its hash-pinned pytest when python is declared. The base's own /usr/local
# holds only `fixuid`, which the copy leaves in place.
COPY --from=toolchain /opt/ /opt/
COPY --from=toolchain /usr/local/ /usr/local/

# ⚠️ The runner's Python links libreadline.so.8 from lib-dynload, and this base
# does not carry it (measured, TC-01/7): `import readline` fails without it.
# From snapshot.debian.org at a pinned timestamp and exact versions; only the
# snapshot is consulted, so nothing arrives from a moving archive.
ARG WITH_READLINE
ARG READLINE_SNAPSHOT
ARG READLINE_PACKAGES
RUN if [ "${WITH_READLINE}" = yes ]; then \
      mkdir -p /tmp/apt-parts \
   && echo "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${READLINE_SNAPSHOT} trixie main" \
          > /tmp/apt-snapshot.list \
   && set -- -o Dir::Etc::SourceList=/tmp/apt-snapshot.list -o Dir::Etc::SourceParts=/tmp/apt-parts \
          -o "Acquire::http::User-Agent=Example/0.1 (+https://example.invalid)" \
   && export DEBIAN_FRONTEND=noninteractive \
   && apt-get "$@" update \
   && apt-get "$@" install -y --no-install-recommends ${READLINE_PACKAGES} \
   && rm -rf /var/lib/apt/lists/* /tmp/apt-parts /tmp/apt-snapshot.list; \
    fi \
 && ldconfig

# ⭐ ENV reaches `docker exec` and every non-login shell.
ENV JAVA_HOME=/opt/java/openjdk
ENV PATH=/opt/java/openjdk/bin:/opt/maven/bin:/opt/gradle/bin:/opt/kotlinc/bin:/opt/node/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# TypeScript into the runner's Node prefix, so `tsc` sits beside `node`. From the
# pinned tarball, with no network: nothing is resolved from a registry.
ARG WITH_TYPESCRIPT
RUN --network=none --mount=type=bind,from=fetch,source=/fetch,target=/tmp/fetch \
    if [ "${WITH_TYPESCRIPT}" = yes ]; then \
      HOME=/tmp/npm-home npm install -g --offline --no-audit --no-fund /tmp/fetch/typescript.tgz \
   && rm -rf /tmp/npm-home; \
    fi

# Extensions are installed at BUILD time into a directory IN the image, never
# onto a volume: an extension on a volume outlives the image, and after an
# upgrade the reader runs old extensions against a new toolchain.
# ⭐ With no network, from the pinned files only: nothing is quietly fetched
# from a marketplace. ⛔ Then the installed set must EQUAL the pins and every
# declared dependency must be installed, or the build fails naming the id —
# a marketplace that stops serving an id otherwise yields an image with no
# language support that still builds and starts.
ARG EXPECTED_EXTENSIONS
COPY docker/editor/verify_extensions.js /tmp/verify_extensions.js
RUN --network=none --mount=type=bind,from=fetch,source=/fetch,target=/tmp/fetch \
    set -eu; \
    mkdir -p /opt/code-server/extensions; \
    for vsix in /tmp/fetch/*.vsix; do \
      code-server --extensions-dir /opt/code-server/extensions --install-extension "$vsix" >/dev/null 2>&1 \
        || { echo "installing $(basename "$vsix") failed" >&2; exit 1; }; \
    done; \
    code-server --extensions-dir /opt/code-server/extensions --list-extensions --show-versions 2>/dev/null \
      | /usr/lib/code-server/lib/node /tmp/verify_extensions.js /opt/code-server/extensions ${EXPECTED_EXTENSIONS}; \
    rm -rf /tmp/verify_extensions.js /root/.local/share/code-server /root/.config/code-server; \
    chown -R 1000:1000 /opt/code-server/extensions; \
    chmod -R a+rX /opt/code-server/extensions

# ⭐ A LOGIN shell rebuilds PATH from /etc/profile, which assigns it outright
# (measured on this base) and silently drops /opt: a tool works under
# `docker exec` and is "command not found" in the integrated terminal. So the
# same PATH is set again from profile.d.
RUN printf '%s\n' \
      'export JAVA_HOME=/opt/java/openjdk' \
      'export PATH=/opt/java/openjdk/bin:/opt/maven/bin:/opt/gradle/bin:/opt/kotlinc/bin:/opt/node/bin:$PATH' \
      > /etc/profile.d/10-editor-toolchain.sh

# The settings seed. Its Java runtime name is derived from pins.json at build
# time, never written by hand (TC-01/5).
ARG JAVA_RUNTIME
COPY docker/editor/entrypoint.sh /opt/code-server/entrypoint.sh
COPY docker/editor/seed/settings.json /opt/code-server/seed/settings.json
RUN sed -i "s/@JAVA_RUNTIME@/${JAVA_RUNTIME}/" /opt/code-server/seed/settings.json \
 && ! grep -q '@JAVA_RUNTIME@' /opt/code-server/seed/settings.json \
 && chmod 755 /opt/code-server/entrypoint.sh \
 && chmod 644 /opt/code-server/seed/settings.json

# Named volumes are initialised from the image. Docker creates a mount point
# that does not exist in the image owned by root, and code-server then cannot
# write its own config (EACCES on /home/coder/.config). So each is created here,
# owned by the runtime uid.
RUN install -d -o 1000 -g 1000 /home/coder/.config /home/coder/.local /home/coder/.gradle

# ⛔ /opt holds exactly the declared set's trees plus code-server's, and every
# toolchain reports the version the pins record — under `sh -c` (what
# `docker exec` gets) AND under `bash -lc` (what the integrated terminal gets).
# An image that fails either is not tagged.
ARG CHECKS
ARG OPT_EXPECTED
RUN set -eu; \
    held="$(LC_ALL=C ls -A /opt | xargs)"; \
    [ "$held" = "${OPT_EXPECTED}" ] \
      || { echo "/opt holds '$held'; the declared set places '${OPT_EXPECTED}'" >&2; exit 1; }; \
    for shell in "sh -c" "bash -lc"; do \
      printf '%s\n' "${CHECKS}" | while IFS='|' read -r name command expect; do \
        [ -n "$name" ] || continue; \
        out="$(HOME=/tmp/check-home $shell "$command" 2>&1)" \
          || { echo "$name: '$command' failed under $shell" >&2; exit 1; }; \
        printf '%s' "$out" | grep -qF -- "$expect" \
          || { echo "$name: '$command' does not report '$expect' under $shell" >&2; exit 1; }; \
        echo "$shell: $name: $expect"; \
      done; \
    done; \
    rm -rf /tmp/check-home

ARG DECLARED
ARG RUNNER_IMAGE
LABEL org.studyforge.editor.runtimes="${DECLARED}" \
      org.studyforge.editor.runner="${RUNNER_IMAGE}"
USER 1000

# The base bakes `--bind-addr 0.0.0.0:8080 .` into its ENTRYPOINT, so a compose
# `command:` would be APPENDED after those arguments. Both are re-declared: the
# entrypoint takes no arguments of its own, and CMD is the whole code-server
# command line, which a compose file replaces outright (its run shape is TC-05's).
ENTRYPOINT ["/opt/code-server/entrypoint.sh"]
CMD ["--bind-addr", "0.0.0.0:8080", "--extensions-dir=/opt/code-server/extensions", "."]
