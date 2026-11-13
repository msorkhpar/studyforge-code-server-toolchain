"""Plan, tag and build a GPU variant image (`variants/<name>.json`) on its profile's image.

Run from the component root:

    python3 docker/variant_gpu/variant_build.py --variant optimization-gpu --image runner --print-tag
    python3 docker/variant_gpu/variant_build.py --variant optimization-gpu --image runner --print-plan
    python3 docker/variant_gpu/variant_build.py --variant optimization-gpu --image runner \\
        --base-digest sha256:<the PROFILE image's digest> --label <project>

`--base-digest` is the digest of the profile image this variant layers on (the image
`package_build.py --profile optimization --print-tag` names), which must already be built: nothing is
pulled or rebuilt. `--target highs-check` builds only the HiGHS half and proves it (a small image).
`--label` puts `com.local.compose.project=<value>` on the image, so a scratch build can be pruned by it.
Every refusal happens before Docker starts.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import variant_plan  # noqa: E402
import profile_build  # noqa: E402

profile_plan = variant_plan.profile_plan
PROJECT_LABEL = "com.local.compose.project"
TARGETS = ("variant", "highs-check")


def docker_command(root: Path, built: variant_plan.Plan, base_digest: str, label: str | None = None,
                   target: str = "variant") -> list[str]:
    if not profile_plan._DIGEST.match(base_digest or ""):
        raise profile_plan.Refused("the profile image is named by its sha256 image digest: --base-digest sha256:<64 hex>")
    args = dict(built.build_args, PROFILE_BASE=f"{built.profile_tag}@{base_digest}")
    tag = built.tag if target == "variant" else f"{built.tag}-{target}"
    command = ["docker", "build", "--progress=plain", "--platform", built.platform, "--pull=false",
               "-f", str(Path(root) / variant_plan.DOCKERFILE), "-t", tag]
    if target != "variant":
        command += ["--target", target]
    if label:
        command += ["--label", f"{PROJECT_LABEL}={label}"]
    for key in sorted(args):
        command += ["--build-arg", f"{key}={args[key]}"]
    command += ["--build-context", f"variant-files={Path(root) / variant_plan.VARIANTS_DIR / built.variant}",
                "--build-context", f"variant-recipe={Path(root) / variant_plan.RECIPE}"]
    return command + [str(profile_build.empty_context(root))]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--variant", required=True)
    parser.add_argument("--image", choices=profile_plan.IMAGES, required=True)
    parser.add_argument("--runtimes", default="", help="the base's declared set; default: what the profile layers on")
    parser.add_argument("--platform", default="linux/amd64")
    parser.add_argument("--root", default=str(variant_plan.COMPONENT))
    parser.add_argument("--base-digest", default=None, help="the PROFILE image's sha256 digest (a build needs it)")
    parser.add_argument("--label", default=None, help=f"a {PROJECT_LABEL} value put on the built image")
    parser.add_argument("--target", choices=TARGETS, default="variant")
    parser.add_argument("--print-tag", action="store_true")
    parser.add_argument("--print-plan", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    names = [name for name in args.runtimes.split(",") if name]
    try:
        built = variant_plan.plan(root, args.variant, args.image, names, args.platform)
        if args.print_tag:
            print(built.tag)
            return 0
        if args.print_plan:
            print(json.dumps(dataclasses.asdict(built), indent=2, sort_keys=True))
            return 0
        variant_plan.check(root, args.variant, variant_plan.load(root, args.variant), args.platform)
        command = docker_command(root, built, args.base_digest, args.label, args.target)
    except profile_plan.Refused as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 2
    done = subprocess.run(command, stdin=subprocess.DEVNULL)
    if done.returncode == 0:
        print(command[command.index("-t") + 1])
    return done.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
