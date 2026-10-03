"""Plan, tag and build a profile image whose entries include `python-wheels` or `npm-packages`.

Run from the component root:

    python3 docker/profile_packages/package_build.py --profile claude-sdks --image runner --print-tag
    python3 docker/profile_packages/package_build.py --profile claude-sdks --image runner --print-plan
    python3 docker/profile_packages/package_build.py --profile claude-sdks --image runner --base-digest sha256:<base digest>

It builds the profile image with `docker/profile/profile_build.py`'s own command (the `project`
and `editor-extension` entries), then layers the packages on it with `docker/profile_packages/Dockerfile`
and removes the intermediate image. A profile with none of these entries builds exactly as
`profile_build.py` builds it, and gets the same tag. Every refusal happens before Docker starts:
a placeholder, a requirements file or lockfile that does not match its pin, a line with no hash,
a lockfile entry with no integrity.
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
sys.path.insert(0, str(HERE.parents[1] / "docker" / "profile"))
import package_kinds  # noqa: E402
import profile_build  # noqa: E402
import profile_plan  # noqa: E402

LABEL = "org.studyforge.profile.build"


def docker_command(root: Path, built: package_kinds.Plan, intermediate: str, label: str | None = None) -> list[str]:
    args = dict(built.build_args, PROFILE_IMAGE=intermediate)
    command = ["docker", "build", "--progress=plain", "--platform", built.base.platform, "--pull=false",
               "-f", str(Path(root) / package_kinds.DOCKERFILE), "-t", built.tag]
    if label:
        command += ["--label", f"{LABEL}={label}"]
    for key in sorted(args):
        command += ["--build-arg", f"{key}={args[key]}"]
    files = Path(root) / profile_plan.PROFILES_DIR / built.profile
    command += ["--build-context", f"profile-files={files}",
                "--build-context", f"packages-recipe={Path(root) / package_kinds.RECIPE}",
                "--build-context", f"warmers={Path(root) / profile_plan.WARMERS}"]
    return command + [str(profile_build.empty_context(root))]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", required=True)
    parser.add_argument("--image", choices=profile_plan.IMAGES, required=True)
    parser.add_argument("--runtimes", default="", help="the base's declared set; default: what the profile layers on")
    parser.add_argument("--platform", default=None)
    parser.add_argument("--root", default=str(package_kinds.COMPONENT))
    parser.add_argument("--base-digest", default=None, help="the base image's sha256 digest (a build needs it)")
    parser.add_argument("--label", default=None, help="a label value put on the built images, so a scratch build can be pruned by it")
    parser.add_argument("--print-tag", action="store_true")
    parser.add_argument("--print-plan", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    names = [name for name in args.runtimes.split(",") if name]
    platform = args.platform or profile_build.host_platform()
    try:
        built = package_kinds.plan(root, args.profile, args.image, names, platform)
        if args.print_tag:
            print(built.tag)
            return 0
        if args.print_plan:
            print(json.dumps(dataclasses.asdict(built), indent=2, sort_keys=True))
            return 0
        profile = profile_plan.load(root, args.profile)
        waiting = profile_plan.unpinned(profile)
        if waiting:
            raise profile_plan.Refused(f"{waiting} still read {profile_plan.PLACEHOLDER}; pin them before a build")
        profile_plan.check_projects(root, args.profile, profile)
        profile_plan.check_extensions(args.profile, profile, platform)
        package_kinds.check(root, args.profile, profile, platform)
        # ⭐ A profile whose entries are all package kinds needs nothing from the profile recipe, so the
        # package layer starts FROM the base by tag and digest; otherwise it starts from the profile image.
        legacy = package_kinds.has_legacy_entries(profile) or not package_kinds.has_packages(profile)
        first = profile_build.docker_command(root, built.base, args.base_digest) if legacy else None
        if first and args.label:
            first[first.index("-t"):first.index("-t")] = ["--label", f"{LABEL}={args.label}"]
        start = built.base.tag if legacy else profile_plan.base_reference(built.base, args.base_digest)
        second = docker_command(root, built, start, args.label) if package_kinds.has_packages(profile) else None
    except profile_plan.Refused as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 2
    if first:
        done = subprocess.run(first, stdin=subprocess.DEVNULL)
        if done.returncode or second is None:
            if not done.returncode:
                print(built.tag)
            return done.returncode
    done = subprocess.run(second, stdin=subprocess.DEVNULL)
    if first:
        subprocess.run(["docker", "rmi", built.base.tag], stdin=subprocess.DEVNULL, capture_output=True)
    if done.returncode == 0:
        print(built.tag)
    return done.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
