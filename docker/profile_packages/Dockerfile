# The profile's PACKAGE layer: `python-wheels` and `npm-packages` entries, on the image the
# profile's own recipe (`docker/profile/Dockerfile`) already built.
#
# ⛔ Build it ONLY through `docker/profile_packages/package_build.py`, which builds the profile image first,
# names it here as PROFILE_IMAGE and passes every value below from `profiles/<name>.json`.
# No ARG carries a default. The base and the profile's own layer are never changed by this file.
ARG PROFILE_IMAGE
ARG PROFILE_HAS_NPM
ARG PROFILE_HAS_PROJECTS

# ------------------------------------ the fetch stage: the ONLY stage with a network
# Wheels are downloaded with `--require-hashes` (and `--only-binary=:all:` unless the entry says
# `allow_sdist`), npm packages with `npm ci` into an empty cache. A wrong hash or integrity stops
# the build here. The stage runs in the profile image so the wheels match its Python.
FROM ${PROFILE_IMAGE} AS fetch
USER root
ARG PROFILE_WHEELS
ARG PROFILE_NPM
RUN --mount=type=bind,from=profile-files,target=/files \
    --mount=type=bind,from=packages-recipe,target=/recipe \
    sh /recipe/fetch.sh

# ------------------------------------ the offline install and proof
FROM ${PROFILE_IMAGE} AS installed
USER root
ARG PROFILE_WHEELS
ARG PROFILE_NPM
LABEL org.studyforge.profile.packages="${PROFILE_WHEELS}${PROFILE_NPM}"
COPY --from=fetch /fetched /opt/profile/fetched
RUN --network=none \
    --mount=type=bind,from=profile-files,target=/files \
    --mount=type=bind,from=packages-recipe,target=/recipe \
    sh /recipe/install.sh

# ------------------------------------ the profile's `project` entries
# Each project is a Gradle multi-project under profiles/<name>/, arriving as the read-only named
# context `profile-files`; the warmers in prime/ arrive as `warmers`. They are the course layer's own
# warm steps, unchanged: `warm` builds the project with the network into one seed, every file checked
# against the project's verification-metadata.xml, and the warmed artifacts are kept as a READ-ONLY
# dependency cache (GRADLE_RO_DEP_CACHE), never as a Gradle user home. The proof then builds a fresh
# copy of each project in an EMPTY Gradle user home with NO network. A profile with no project entry
# never runs this stage, and its image is as it was.
FROM installed AS warmed
ARG PROFILE_PROJECTS
RUN --mount=type=bind,from=profile-files,target=/tmp/projects \
    --mount=type=bind,from=warmers,target=/tmp/warmers \
    set -eu; \
    mkdir -p /opt/profile/gradle-ro-cache; \
    for path in ${PROFILE_PROJECTS}; do \
      sh /tmp/warmers/warm-gradle.sh warm "/tmp/projects/${path}" /opt/profile/seed; \
    done; \
    if [ -d /opt/profile/seed/caches/modules-2 ]; then \
      cp -R /opt/profile/seed/caches/modules-2 /opt/profile/gradle-ro-cache/modules-2; \
    fi; \
    rm -rf /opt/profile/seed /root/.m2 /root/.gradle /root/.local/share/kotlin /tmp/kotlin-daemon*; \
    chmod -R a+rX,a-w /opt/profile/gradle-ro-cache; \
    chmod a+rX,a-w /opt/profile
ENV GRADLE_RO_DEP_CACHE=/opt/profile/gradle-ro-cache
RUN --network=none \
    --mount=type=bind,from=profile-files,target=/tmp/projects \
    --mount=type=bind,from=warmers,target=/tmp/warmers \
    set -eu; \
    for path in ${PROFILE_PROJECTS}; do \
      home="$(mktemp -d)"; \
      sh /tmp/warmers/warm-gradle.sh prove "/tmp/projects/${path}" "${home}"; \
      rm -rf "${home}"; \
    done; \
    rm -rf /root/.m2 /root/.gradle /root/.local/share/kotlin /tmp/kotlin-daemon*

FROM installed AS projects-0
FROM warmed AS projects-1
FROM projects-${PROFILE_HAS_PROJECTS} AS ready

# ⭐ npm names its read-only cache only when an `npm-packages` entry exists; a profile with
# wheels alone leaves npm's own cache location as the base had it.
FROM ready AS env-npm-1
ENV npm_config_cache=/opt/profile/npm-cache
FROM ready AS env-npm-0

FROM env-npm-${PROFILE_HAS_NPM}
ARG PROFILE_RESTORE_USER
USER ${PROFILE_RESTORE_USER}
