# The profile's PACKAGE layer: `python-wheels` and `npm-packages` entries, on the image the
# profile's own recipe (`docker/profile/Dockerfile`) already built.
#
# ⛔ Build it ONLY through `docker/profile_packages/package_build.py`, which builds the profile image first,
# names it here as PROFILE_IMAGE and passes every value below from `profiles/<name>.json`.
# No ARG carries a default. The base and the profile's own layer are never changed by this file.
ARG PROFILE_IMAGE
ARG PROFILE_HAS_NPM

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

# ⭐ npm names its read-only cache only when an `npm-packages` entry exists; a profile with
# wheels alone leaves npm's own cache location as the base had it.
FROM installed AS env-npm-1
ENV npm_config_cache=/opt/profile/npm-cache
FROM installed AS env-npm-0

FROM env-npm-${PROFILE_HAS_NPM}
ARG PROFILE_RESTORE_USER
USER ${PROFILE_RESTORE_USER}
