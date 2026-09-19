# check=skip=InvalidDefaultArgInFrom
# ⭐ That directive is deliberate: the linter warns that an ARG used in FROM has
# no default, and having NO default is the point (see below).
#
# The RUNNER image (TC-00): the runtimes one corpus DECLARES, pinned, and nothing else.
#
# ⛔ Build it ONLY through `docker/minimal/build.py`, from the component root:
#     python3 docker/minimal/build.py --runtimes java,maven
# Every ARG below is passed from `pins.json` and carries NO default, so a build
# that bypasses the pin file fails on an empty argument instead of quietly
# choosing a version (the epic: this image must never be a second place a
# version is chosen).
#
# ⛔ What this image is NOT: an editor. No IDE, no extensions, no port, never
# served to a browser, and it must never grow into the code-server image (TC-01).
# ⛔ No Docker socket is mounted into it and it carries no `docker` CLI: the
# runner reaches it from OUTSIDE with `docker exec` (studyforge spec §8.3).
#
# How a runtime arrives, and why each is a pin:
#   * images by multi-arch INDEX digest — a content address verifies itself;
#   * archives by `ADD --checksum` against the sha256 RECORDED in pins.json —
#     the build fetches no checksum, so a host that serves a different file
#     fails the build instead of agreeing with itself;
#   * Debian packages from snapshot.debian.org at a pinned timestamp and exact
#     version — apt checks the signed Release with the base image's keyring.
#
# How a runtime is LEFT OUT: each optional runtime has a `-yes` and a `-no`
# stage, and `FROM <name>-${WITH_<NAME>}` selects one. BuildKit never builds a
# stage nothing selects, and a `-no` stage holds only an empty `/opt` (which
# every base already has), so an undeclared runtime is absent from the image,
# not merely off PATH.
# ⛔ A `-no` stage is NEVER bare `scratch` (W374). Measured on BuildKit v0.31.1:
# `COPY --from=<a bare scratch stage> / /` is served from the cache the `-yes`
# twin's COPY recorded on the same base, so once a set with the runtime was
# built on the python base, a `python`-only build came out holding every
# runtime. The `WORKDIR /opt` gives the stage real, content-addressed bytes,
# and `plan.dockerfile_findings` refuses a bare scratch stage.
# ⛔ And the runner stage is KEYED before its first COPY (W379). Measured on the
# same BuildKit (TC-01/13): with a `python`-only runner built, a build of
# `gradle,java,kotlin,node,python` served every `COPY --from=<runtime> / /` from
# the `-no` twin's record and /opt came out empty. Each such COPY is cached on
# two inputs, the runner's layer below it and the selected stage; the second is
# the one a warm cache has matched wrongly, in both directions. So the first
# instruction of the runner stage is a RUN that reads CACHE_KEY, which
# `plan.py` sets to the image's own TAG (the declared set, the architecture and
# the digest of every input). A RUN's cache key carries its build arguments, so
# every layer above it is cached per tag: a record made for one selection, or
# one set of pins, is never a candidate for another, however the second input
# matches. `plan.dockerfile_findings` refuses a stage that copies from a
# selected stage before that RUN.

ARG RUNNER_BASE
ARG UNPACK_IMAGE
ARG JAVA_IMAGE
ARG WITH_JAVA
ARG WITH_MAVEN
ARG WITH_MAVENREPO
ARG WITH_GRADLE
ARG WITH_KOTLIN
ARG WITH_NODE

# --------------------------------------------------------------------------- java
FROM ${JAVA_IMAGE} AS java-image
FROM scratch AS java-no
WORKDIR /opt
FROM scratch AS java-yes
# The JDK is a self-contained tree, so it is copied whole out of the official
# image onto the Debian base (the Temurin images are Ubuntu-based; the tree
# needs only glibc).
COPY --from=java-image /opt/java/openjdk /opt/java/openjdk
FROM java-${WITH_JAVA} AS java

# ------------------------------------------------------------------- unpacking
# A build tool only: the Python image unpacks zips with the standard library.
# It reaches the runner image only when python is DECLARED (then it is the base).
FROM ${UNPACK_IMAGE} AS unpack
WORKDIR /unpack

# ------------------------------------------------------------------------ maven
FROM unpack AS maven-work
ARG MAVEN_URL
ARG MAVEN_SHA256
ADD --checksum=sha256:${MAVEN_SHA256} ${MAVEN_URL} /unpack/maven.tar.gz
RUN mkdir -p /opt/maven \
 && tar -xzf maven.tar.gz -C /opt/maven --strip-components=1 --no-same-owner
FROM scratch AS maven-no
WORKDIR /opt
FROM scratch AS maven-yes
COPY --from=maven-work /opt/maven /opt/maven
FROM maven-${WITH_MAVEN} AS maven

# The generic warm: the plugins and JUnit the SMOKE project needs, and nothing
# a corpus needs (that is TC-03's). ⛔ `mvn -o test` cannot run on an empty
# local repository — an offline Maven cannot even resolve its compiler plugin.
FROM unpack AS maven-fetch
# ⭐ The `-yes` stages by name, not the selected `java` and `maven`: this stage
# is reached only when maven is declared, and naming them makes its layers
# independent of the selection by construction (W379).
COPY --from=java-yes / /
COPY --from=maven-yes / /
COPY docker/minimal/smoke/maven /unpack/smoke
# `-C` is --strict-checksums: every file is checked against Central's own
# checksum as it arrives. That is the host agreeing with itself, which is why
# the files are then checked against pins.json below.
RUN PATH=/opt/java/openjdk/bin:/opt/maven/bin:$PATH \
    mvn -B -C -ntp -Dmaven.repo.local=/opt/maven-repo \
        "-Daether.connector.userAgent=Example/0.1 (+https://example.invalid)" \
        -f /unpack/smoke/pom.xml test \
 && find /opt/maven-repo \( -name '_remote.repositories' -o -name '*.lastUpdated' \
        -o -name 'resolver-status.properties' \) -delete

FROM maven-fetch AS maven-warm
COPY pins.json /unpack/pins.json
COPY docker/minimal/verify_repo.py /unpack/verify_repo.py
RUN python3 /unpack/verify_repo.py /unpack/pins.json /opt/maven-repo

# Used only to RECORD the pins (`build.py --record-maven`), never for an image.
FROM maven-fetch AS maven-record
COPY docker/minimal/verify_repo.py /unpack/verify_repo.py
RUN mkdir /record && python3 /unpack/verify_repo.py --record /opt/maven-repo > /record/maven-warm.json
FROM scratch AS maven-record-out
COPY --from=maven-record /record /

FROM scratch AS mavenrepo-no
WORKDIR /opt
FROM scratch AS mavenrepo-yes
COPY --from=maven-warm /opt/maven-repo /opt/maven-repo
FROM mavenrepo-${WITH_MAVENREPO} AS mavenrepo

# ----------------------------------------------------------------------- gradle
FROM unpack AS gradle-work
ARG GRADLE_URL
ARG GRADLE_SHA256
ADD --checksum=sha256:${GRADLE_SHA256} ${GRADLE_URL} /unpack/gradle.zip
# `zipfile` drops the execute bit, so the launcher gets it back explicitly.
RUN python3 -m zipfile -e gradle.zip /unpack/out \
 && mv /unpack/out/gradle-* /opt/gradle \
 && chmod 755 /opt/gradle/bin/gradle
FROM scratch AS gradle-no
WORKDIR /opt
FROM scratch AS gradle-yes
COPY --from=gradle-work /opt/gradle /opt/gradle
FROM gradle-${WITH_GRADLE} AS gradle

# ----------------------------------------------------------------------- kotlin
FROM unpack AS kotlin-work
ARG KOTLIN_URL
ARG KOTLIN_SHA256
ADD --checksum=sha256:${KOTLIN_SHA256} ${KOTLIN_URL} /unpack/kotlin.zip
RUN python3 -m zipfile -e kotlin.zip /opt \
 && chmod 755 /opt/kotlinc/bin/*
FROM scratch AS kotlin-no
WORKDIR /opt
FROM scratch AS kotlin-yes
COPY --from=kotlin-work /opt/kotlinc /opt/kotlinc
FROM kotlin-${WITH_KOTLIN} AS kotlin

# ------------------------------------------------------------------------- node
FROM unpack AS node-work
ARG NODE_URL
ARG NODE_SHA256
ADD --checksum=sha256:${NODE_SHA256} ${NODE_URL} /unpack/node.tar.gz
RUN mkdir -p /opt/node \
 && tar -xzf node.tar.gz -C /opt/node --strip-components=1 --no-same-owner
FROM scratch AS node-no
WORKDIR /opt
FROM scratch AS node-yes
COPY --from=node-work /opt/node /opt/node
FROM node-${WITH_NODE} AS node

# ----------------------------------------------------------------------- runner
FROM ${RUNNER_BASE} AS runner
# ⛔ FIRST, before any COPY (W379, see the top of this file): every layer above
# this one is cached per image tag. It writes nothing.
ARG CACHE_KEY
RUN : "runner ${CACHE_KEY}"
COPY --from=java / /
COPY --from=maven / /
COPY --from=mavenrepo / /
COPY --from=gradle / /
COPY --from=kotlin / /
COPY --from=node / /

# ⛔ No JAVA_HOME: it would point at nothing in an image built without java,
# and every launcher here finds `java` on PATH.
ENV PATH=/opt/java/openjdk/bin:/opt/maven/bin:/opt/gradle/bin:/opt/kotlinc/bin:/opt/node/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# ⭐ ENV reaches `docker exec`; a LOGIN shell rebuilds PATH from /etc/profile
# and silently drops /opt, so the same PATH is set again from profile.d.
RUN printf '%s\n' \
      'export PATH=/opt/java/openjdk/bin:/opt/maven/bin:/opt/gradle/bin:/opt/kotlinc/bin:/opt/node/bin:$PATH' \
      > /etc/profile.d/10-runner-toolchain.sh

ARG WITH_PYTHON
ARG PYTEST_REQUIREMENTS
RUN if [ "${WITH_PYTHON}" = yes ]; then \
      printf '%s\n' "${PYTEST_REQUIREMENTS}" > /tmp/requirements.txt \
   && pip install --no-cache-dir --no-deps --require-hashes --root-user-action=ignore \
          -r /tmp/requirements.txt \
   && rm /tmp/requirements.txt; \
    fi

ARG WITH_SQLITE
ARG SQLITE_SNAPSHOT
ARG SQLITE_PACKAGES
# ⭐ Only the snapshot is consulted: the image's own sources are switched off
# for this one command, so nothing arrives from a moving archive.
RUN if [ "${WITH_SQLITE}" = yes ]; then \
      mkdir -p /tmp/apt-parts \
   && echo "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${SQLITE_SNAPSHOT} trixie main" \
          > /tmp/apt-snapshot.list \
   && set -- -o Dir::Etc::SourceList=/tmp/apt-snapshot.list -o Dir::Etc::SourceParts=/tmp/apt-parts \
          -o "Acquire::http::User-Agent=Example/0.1 (+https://example.invalid)" \
   && export DEBIAN_FRONTEND=noninteractive \
   && apt-get "$@" update \
   && apt-get "$@" install -y --no-install-recommends ${SQLITE_PACKAGES} \
   && rm -rf /var/lib/apt/lists/* /tmp/apt-parts /tmp/apt-snapshot.list; \
    fi

# ⛔ Every declared runtime reports the version pins.json records, or the build
# fails naming it. An image whose contents do not match its pins is not shipped.
ARG CHECKS
ARG OPT_EXPECTED
ENV HOME=/tmp
# ⛔ /opt holds exactly what the declared set places there, or the build fails
# naming both (W374): an undeclared runtime is ABSENT, and this is where the
# image says so before it is tagged.
RUN held="$(ls -A /opt | xargs)"; \
    [ "$held" = "${OPT_EXPECTED}" ] \
      || { echo "/opt holds '$held'; the declared set places '${OPT_EXPECTED}'" >&2; exit 1; } \
 && printf '%s\n' "${CHECKS}" | while IFS='|' read -r name command expect; do \
      [ -n "$name" ] || continue; \
      out="$(sh -c "$command" 2>&1)" || { echo "$name: '$command' failed" >&2; exit 1; }; \
      printf '%s' "$out" | grep -qF -- "$expect" \
        || { echo "$name: '$command' does not report '$expect' (pins.json)" >&2; exit 1; }; \
      echo "$name: $expect"; \
    done \
 && rm -rf /tmp/* /tmp/.[!.]*

ARG DECLARED
LABEL org.studyforge.runner.runtimes="${DECLARED}"
WORKDIR /work
# The reader starts this container and the runner only probes and execs into
# it, so it idles. Run it with `--init` (see the README) so the idle process is
# reaped and a stop is prompt.
CMD ["sleep", "infinity"]
