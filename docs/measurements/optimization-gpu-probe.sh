#!/bin/sh
# GPU probes of the optimization-gpu variant (see optimization-gpu-probe.py). Needs a Docker that reaches a
# GPU (`docker run --gpus all` works). Prints JSON lines; nothing is written outside the container.
#
#   sh docs/measurements/optimization-gpu-probe.sh <gpu image> [transport size, default 300]
#   sh docs/measurements/optimization-gpu-probe.sh <gpu image> cuopt      # optimization-gpu-cuopt-probe.py
set -eu
image="$1"
arg="${2:-300}"
here="$(cd "$(dirname "$0")" && pwd)"
script=optimization-gpu-probe.py
[ "$arg" = cuopt ] && script=optimization-gpu-cuopt-probe.py && arg=""
exec docker run --rm --gpus all --network none -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$here:/probe:ro" "$image" python3 "/probe/$script" $arg
