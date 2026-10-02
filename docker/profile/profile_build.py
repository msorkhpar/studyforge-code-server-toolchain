"""Plan, tag and build a profile image: the shared base for a declared set plus a profile's additions.

Run from the component root:

    python3 docker/profile/profile_build.py --profile jvm-frameworks --image runner --print-tag
    python3 docker/profile/profile_build.py --profile jvm-frameworks --image editor --print-plan
    python3 docker/profile/profile_build.py --profile jvm-frameworks --image runner \
        --base-digest sha256:<the base image's digest>

`--print-tag` prints the tag and `--print-plan` the whole plan as JSON; neither touches Docker.
A build needs `--base-digest`, so it starts FROM the base by tag and digest, and it is refused
while any of the profile's entries still reads TO-BE-PINNED, and a `project` entry whose directory
or verification-metadata checksum does not match its pin is refused by name before Docker starts.
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
import profile_plan  # noqa: E402

COMPONENT = profile_plan.COMPONENT


def host_platform() -> str:
    import platform
    machine = platform.machine().lower()
    return {"x86_64": "linux/amd64", "amd64": "linux/amd64", "aarch64": "linux/arm64", "arm64": "linux/arm64"}.get(
        machine, f"linux/{machine}")


def empty_context(root: Path) -> Path:
    """A profile needs no files from the repository, so its build context is an empty directory."""
    path = Path(root) / ".work" / "profile-context"
    path.mkdir(parents=True, exist_ok=True)
    return path


def docker_command(root: Path, built: profile_plan.Plan, base_digest: str) -> list[str]:
    args = dict(built.build_args, BASE_IMAGE=profile_plan.base_reference(built, base_digest))
    command = ["docker", "build", "--progress=plain", "--platform", built.platform, "--pull=false",
               "-f", str(Path(root) / profile_plan.DOCKERFILE), "-t", built.tag]
    for key in sorted(args):
        command += ["--build-arg", f"{key}={args[key]}"]
    # The projects a profile warms and the warmers that warm them arrive as named contexts, read-only.
    # A profile with no project directory (an extension-only profile) hands the empty context instead.
    projects = Path(root) / profile_plan.PROFILES_DIR / built.profile
    command += ["--build-context", f"profile-projects={projects if projects.is_dir() else empty_context(root)}",
                "--build-context", f"warmers={Path(root) / profile_plan.WARMERS}",
                "--build-context", f"profile-recipe={Path(root) / profile_plan.RECIPE}"]
    return command + [str(empty_context(root))]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", required=True)
    parser.add_argument("--image", choices=profile_plan.IMAGES, required=True)
    parser.add_argument("--runtimes", default="", help="the base's declared set; default: what the profile layers on")
    parser.add_argument("--platform", default=None)
    parser.add_argument("--root", default=str(COMPONENT))
    parser.add_argument("--base-digest", default=None, help="the base image's sha256 digest (a build needs it)")
    parser.add_argument("--print-tag", action="store_true")
    parser.add_argument("--print-plan", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    names = [name for name in args.runtimes.split(",") if name]
    try:
        built = profile_plan.plan(root, args.profile, args.image, names, args.platform or host_platform())
        if args.print_tag:
            print(built.tag)
            return 0
        if args.print_plan:
            print(json.dumps(dataclasses.asdict(built), indent=2, sort_keys=True))
            return 0
        waiting = profile_plan.unpinned(profile_plan.load(root, args.profile))
        if waiting:
            raise profile_plan.Refused(f"{waiting} still read {profile_plan.PLACEHOLDER}; pin them before a build")
        profile_plan.check_projects(root, args.profile, profile_plan.load(root, args.profile))
        profile_plan.check_extensions(args.profile, profile_plan.load(root, args.profile), built.platform)
        command = docker_command(root, built, args.base_digest)
    except profile_plan.Refused as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 2
    completed = subprocess.run(command, stdin=subprocess.DEVNULL)
    if completed.returncode == 0:
        print(built.tag)
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
