# check=skip=InvalidDefaultArgInFrom
# ⭐ That directive is deliberate: the linter warns that an ARG used in FROM has no default, and having
# NO default is the point: every value comes from `variants/<name>.json` through `variant_build.py`.
#
# A GPU VARIANT image: the optimization PROFILE's runner, plus HiGHS built with CUDA (highspy) and
# NVIDIA cuOpt in a venv of its own. It is optional; no default image is changed by this file.
#
# ⛔ Build it ONLY through `docker/variant_gpu/variant_build.py`, which names the profile image by tag
# AND digest (PROFILE_BASE) and passes every other value below. The profile image is never rebuilt.
#
# Stages:
#   fetch-cuda, fetch-cuopt, highs-source, tools: the ONLY steps with a network. Wheels by
#     `--require-hashes`, the HiGHS archive by `ADD --checksum`, the compiler from a pinned
#     snapshot.debian.org timestamp at exact versions.
#   highs-build: compiles highspy with NO network. The compiler (g++, cmake, make, ninja) and the build
#     venv live in this stage only; the image receives one wheel from it.
#   highs-check: the profile image + the CUDA libraries + that wheel, proved: the HiGHS half alone, for a
#     machine with too little disk for cuOpt (and for the HiGHS GPU probes there). It is not the variant.
#   the last stage: the variant itself, installed with NO network and proved.
ARG PROFILE_BASE

# ------------------------------------ the CUDA wheels, fetched (they compile HiGHS and run it)
FROM ${PROFILE_BASE} AS fetch-cuda
USER root
ARG CUDA_REQUIREMENTS
ARG HIGHS_BUILD_REQUIREMENTS
RUN --mount=type=bind,from=variant-files,target=/files \
    set -eu; \
    mkdir -p /fetched/cuda /fetched/build; \
    python3 -m pip download --no-cache-dir --require-hashes --only-binary=:all: --no-deps \
      --dest /fetched/cuda -r "/files/${CUDA_REQUIREMENTS}"; \
    python3 -m pip download --no-cache-dir --require-hashes --only-binary=:all: --no-deps \
      --dest /fetched/build -r "/files/${HIGHS_BUILD_REQUIREMENTS}"; \
    rm -rf /root/.cache

# ------------------------------------ the rest of cuOpt's closure, fetched
FROM ${PROFILE_BASE} AS fetch-cuopt
USER root
ARG VENV_REQUIREMENTS
ARG CUDA_REQUIREMENTS
RUN --mount=type=bind,from=variant-files,target=/files \
    set -eu; \
    mkdir -p /fetched/cuopt; \
    for req in ${VENV_REQUIREMENTS}; do \
      [ "${req}" = "${CUDA_REQUIREMENTS}" ] && continue; \
      python3 -m pip download --no-cache-dir --require-hashes --only-binary=:all: --no-deps \
        --dest /fetched/cuopt -r "/files/${req}"; \
    done; \
    rm -rf /root/.cache

# ------------------------------------ the HiGHS source archive, by its pinned digest
FROM ${PROFILE_BASE} AS highs-source
ARG HIGHS_URL
ARG HIGHS_SHA256
ADD --checksum=sha256:${HIGHS_SHA256} ${HIGHS_URL} /src/highs.tar.gz

# ------------------------------------ the compiler, from a pinned Debian snapshot (build stage only)
FROM ${PROFILE_BASE} AS tools
USER root
ARG APT_SNAPSHOT
ARG APT_PACKAGES
# ⭐ Only the snapshot is consulted: the image's own sources are switched off for this one command.
RUN set -eu; \
    mkdir -p /tmp/apt-parts; \
    echo "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${APT_SNAPSHOT} trixie main" > /tmp/apt-snapshot.list; \
    set -- -o Dir::Etc::SourceList=/tmp/apt-snapshot.list -o Dir::Etc::SourceParts=/tmp/apt-parts \
           -o "Acquire::http::User-Agent=Example/0.1 (+https://example.invalid)"; \
    export DEBIAN_FRONTEND=noninteractive; \
    apt-get "$@" update; \
    apt-get "$@" install -y --no-install-recommends ${APT_PACKAGES}; \
    rm -rf /var/lib/apt/lists/* /tmp/apt-parts /tmp/apt-snapshot.list

# ------------------------------------ highspy with CUDA, compiled with NO network
FROM tools AS highs-build
ARG CUDA_REQUIREMENTS
ARG HIGHS_BUILD_REQUIREMENTS
ARG HIGHS_EDITS
ARG CUDA_ARCHITECTURES
ARG BUILD_JOBS
ARG VENV
RUN --network=none \
    --mount=type=bind,from=fetch-cuda,source=/fetched,target=/fetched \
    --mount=type=bind,from=highs-source,source=/src,target=/src \
    --mount=type=bind,from=variant-files,target=/files \
    --mount=type=bind,from=variant-recipe,target=/recipe \
    sh /recipe/build_highspy.sh

# ------------------------------------ the HiGHS half, proved on its own (no cuOpt)
FROM ${PROFILE_BASE} AS highs-check
USER root
ARG CUDA_REQUIREMENTS
ARG VENV_REQUIREMENTS
ARG VENV_IMPORTS
ARG HIGHS_REPLACES
ARG VENV
RUN --network=none \
    --mount=type=bind,from=fetch-cuda,source=/fetched/cuda,target=/fetched/cuda \
    --mount=type=bind,from=highs-build,source=/out,target=/out \
    --mount=type=bind,from=variant-files,target=/files \
    --mount=type=bind,from=variant-recipe,target=/recipe \
    sh /recipe/install.sh highs-check

# ------------------------------------ the variant
FROM ${PROFILE_BASE}
USER root
ARG VARIANT_NAME
ARG VARIANT_ADDS
ARG PROFILE_IMAGE
ARG CUDA_REQUIREMENTS
ARG VENV_REQUIREMENTS
ARG VENV_IMPORTS
ARG HIGHS_REPLACES
ARG VENV
LABEL org.studyforge.variant="${VARIANT_NAME}"
LABEL org.studyforge.variant.adds="${VARIANT_ADDS}"
LABEL org.studyforge.variant.device="gpu"
LABEL org.studyforge.variant.profile="${PROFILE_IMAGE}"
# ⭐ The NVIDIA container runtime reads these from the image: with `--gpus all` it mounts the driver's
# CUDA library (compute) and nvidia-smi (utility). Without a GPU they do nothing.
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility
RUN --network=none \
    --mount=type=bind,from=fetch-cuda,source=/fetched/cuda,target=/fetched/cuda \
    --mount=type=bind,from=fetch-cuopt,source=/fetched/cuopt,target=/fetched/cuopt \
    --mount=type=bind,from=highs-build,source=/out,target=/out \
    --mount=type=bind,from=variant-files,target=/files \
    --mount=type=bind,from=variant-recipe,target=/recipe \
    sh /recipe/install.sh full
ENV CUOPT_PYTHON=${VENV}/bin/python
