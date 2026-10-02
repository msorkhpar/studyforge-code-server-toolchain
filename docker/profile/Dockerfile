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
# The additions themselves (fetched by checksum, warmed for offline builds) are added here by
# the row that pins them; until then `profile_build.py` refuses to build a profile whose
# entries still read TO-BE-PINNED.
