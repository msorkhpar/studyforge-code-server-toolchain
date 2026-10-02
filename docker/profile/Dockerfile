# A PROFILE image: the shared base for a declared set, plus the profile's own pinned additions.
#
# ⛔ Build it ONLY through `docker/profile/profile_build.py`, which names the base by tag AND
# digest and passes every value below from `profiles/<name>.json`. No ARG carries a default.
# The base is never rebuilt or changed by this file: a profile is a layer ON it.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG PROFILE_NAME
ARG PROFILE_ADDS
LABEL org.studyforge.profile="${PROFILE_NAME}"
LABEL org.studyforge.profile.adds="${PROFILE_ADDS}"
ARG PROFILE_PROJECTS

# ------------------------------------ the profile's `project` entries
# Each project is a Gradle multi-project under profiles/<name>/, arriving as the read-only named
# context `profile-projects`; the warmers in prime/ arrive as `warmers`. They are the course
# layer's own warm steps, unchanged: `warm` builds the project with the network into one seed,
# every file checked against the project's verification-metadata.xml.
# ⭐ The warmed artifacts are then kept as a READ-ONLY dependency cache, never as a Gradle user
# home: a course prime layered on this image keeps its own GRADLE_USER_HOME, and Gradle reads
# these artifacts from the cache named by GRADLE_RO_DEP_CACHE. With no project entry the
# directory is empty and nothing runs.
RUN --mount=type=bind,from=profile-projects,target=/tmp/projects \
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
    chmod -R a+rX,a-w /opt/profile

ENV GRADLE_RO_DEP_CACHE=/opt/profile/gradle-ro-cache

# ⭐ What the image guarantees, checked before it is tagged: with NO network, a fresh copy of
# each project builds in an EMPTY Gradle user home that has only the read-only cache.
RUN --network=none \
    --mount=type=bind,from=profile-projects,target=/tmp/projects \
    --mount=type=bind,from=warmers,target=/tmp/warmers \
    set -eu; \
    for path in ${PROFILE_PROJECTS}; do \
      home="$(mktemp -d)"; \
      sh /tmp/warmers/warm-gradle.sh prove "/tmp/projects/${path}" "${home}"; \
      rm -rf "${home}"; \
    done; \
    rm -rf /root/.m2 /root/.gradle /root/.local/share/kotlin /tmp/kotlin-daemon*
