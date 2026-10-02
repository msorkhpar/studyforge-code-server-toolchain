"""A profile image's plan, read from `profiles/<name>.json` — pure, no I/O beyond reading files.

**What it is.** A profile is an image LAYERED ON the shared runner or editor base for a
declared set: the base's own tag and digest are its `FROM`, and the profile adds only its own
pinned entries (dependencies now, a runtime later). It is how an input that not every course
needs is added without changing the base.

## ⭐ Why a layer, and why the base is untouched
An image tag is a digest of its build inputs, and every set's tag shares ONE suffix: the digest
over `pins.json`, `docker/minimal/` and, for the editor, `docker/editor/`, `prime/` and
`lockdown/`. A byte changed in any of those moves EVERY published tag. So a new pinned input
may not enter them. A profile's inputs are `profiles/<name>.json` and `docker/profile/`, which
are in no base's inputs, and its tag is computed from them plus the BASE'S OWN TAG. So:

* adding or editing a profile entry, or adding a new profile file, moves no base tag;
* a base change moves the profile's tag, because the base tag is folded in;
* a profile is a thing a course opts into by naming it.

## How you use it
`load(root, name)` reads the profile; `plan(root, name, image, names, platform)` returns a
`Plan` (the tag, the base tag, the build arguments) or raises `Refused`;
`unpinned(profile)` lists the entries still reading `TO-BE-PINNED`, which a build refuses.

## Entry kinds
* `dependency` (and any other kind that carries `coordinates` and `sha256`): read as before.
* `project`: `{"kind": "project", "id": ..., "path": ..., "sha256": ...}`. `path` is a directory
  under `profiles/<name>/` holding a Gradle multi-project (one subproject per distinct dependency
  set); `sha256` is the checksum of its `gradle/verification-metadata.xml`. The directory's bytes,
  and the warmers in `prime/` that warm it, are folded into the profile's tag, and
  `check_projects(root, name, profile)` refuses, naming the entry and the file, a directory or
  checksum file that is missing or does not match, before Docker starts. The recipe warms each
  project with `prime/warm-gradle.sh` and exposes what it warmed as a read-only cache
  (`GRADLE_RO_DEP_CACHE`).

**Depends on.** The editor's and the runner's plans, read-only.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(COMPONENT / "docker" / "editor"))
import editor_plan  # noqa: E402

runner_plan = editor_plan.runner_plan
Refused = runner_plan.Refused

PROFILES_DIR = "profiles"
DOCKERFILE = "docker/profile/Dockerfile"
#: What a profile's tag is a digest of: its own file and this directory. ⛔ Never `pins.json`,
#: `docker/minimal` or any base input: the base's tag, folded in separately, stands for those.
RECIPE = "docker/profile"
#: The warmers a `project` entry is warmed with: read-only here, folded into the tag of a profile
#: that has a project entry (and of no other), so a profile's tag moves when they change.
WARMERS = "prime"
PROJECT = "project"
VERIFICATION = "gradle/verification-metadata.xml"
IMAGES = ("runner", "editor")
PLACEHOLDER = "TO-BE-PINNED"
#: The name a registry sees for each image of a profile: the base's published name plus the profile.
PUBLISHED = {"runner": "studyforge-code-toolchain-runner", "editor": "studyforge-code-toolchain-editor"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class Plan:
    profile: str
    image: str
    names: tuple[str, ...]
    arch: str
    platform: str
    tag: str
    base_tag: str
    published: str
    build_args: dict[str, str]
    projects: tuple[str, ...] = ()


def profile_path(root: Path, name: str) -> Path:
    if not runner_plan.NAME.match(name or ""):
        raise Refused("a profile name is a runtime-id-shaped word")
    return Path(root) / PROFILES_DIR / f"{name}.json"


def load(root: Path, name: str) -> dict:
    path = profile_path(root, name)
    if not path.is_file():
        known = sorted(p.stem for p in (Path(root) / PROFILES_DIR).glob("*.json"))
        raise Refused(f"no profile {name!r}; the profiles are {known}")
    return json.loads(path.read_text(encoding="utf-8"))


def unpinned(profile: dict) -> list[str]:
    """The ids of the entries a build still may not use: a placeholder, or a sha256 that is not one."""
    return [entry["id"] for entry in profile["adds"]
            if PLACEHOLDER in entry.get("coordinates", "") or PLACEHOLDER in entry.get("path", "")
            or not _SHA256.match(entry.get("sha256", ""))]


def projects(profile: dict) -> list[dict]:
    """The profile's `project` entries, in file order."""
    return [entry for entry in profile["adds"] if entry.get("kind") == PROJECT]


def project_dir(root: Path, name: str, entry: dict) -> Path:
    """The entry's directory, which must be a plain relative path under `profiles/<name>/`."""
    where = entry.get("path", "")
    parts = Path(where).parts
    if not where or Path(where).is_absolute() or ".." in parts or "\\" in where:
        raise Refused(f"profile {name!r} project {entry['id']!r}: path {where!r} is not a relative directory under profiles/{name}/")
    return Path(root) / PROFILES_DIR / name / where


def check_projects(root: Path, name: str, profile: dict) -> None:
    """Refuse, by entry and file name, a `project` whose directory or checksum file does not match its pin."""
    for entry in projects(profile):
        directory = project_dir(root, name, entry)
        label = f"profile {name!r} project {entry['id']!r}"
        if not directory.is_dir():
            raise Refused(f"{label}: {directory.relative_to(root).as_posix()} is not a directory")
        metadata = directory / VERIFICATION
        if not metadata.is_file():
            raise Refused(f"{label}: {metadata.relative_to(root).as_posix()} is missing; the project must carry its verification metadata")
        actual = hashlib.sha256(metadata.read_bytes()).hexdigest()
        if actual != entry.get("sha256"):
            raise Refused(f"{label}: {metadata.relative_to(root).as_posix()} has sha256 {actual}, "
                          f"but the profile pins {entry.get('sha256')}")


def _fold(digest, root: Path, files) -> None:
    for file in sorted(files, key=lambda p: p.relative_to(root).as_posix()):
        if "__pycache__" in file.parts:
            continue
        digest.update(file.relative_to(root).as_posix().encode() + b"\0" + file.read_bytes() + b"\0")


def inputs_digest(root: Path, name: str) -> str:
    """sha256 over the profile's file and `docker/profile/`: relative path and bytes, sorted."""
    root = Path(root)
    path = profile_path(root, name)
    files = [path] + sorted(p for p in (root / RECIPE).rglob("*") if p.is_file())
    digest = hashlib.sha256()
    _fold(digest, root, files)
    entries = projects(load(root, name))
    if entries:
        # A project's directory and the warmers that warm it are inputs of this profile only.
        extra = [p for p in (root / WARMERS).rglob("*") if p.is_file()]
        for entry in entries:
            extra += [p for p in project_dir(root, name, entry).rglob("*") if p.is_file()]
        _fold(digest, root, extra)
    return digest.hexdigest()


def base_plan(root: Path, image: str, names, platform: str):
    """The shared base's own plan for the set: exactly what its own `build.py --print-tag` computes."""
    pins = runner_plan.load(root)
    runner = runner_plan.plan(pins, editor_plan.selection(pins, names), platform, runner_plan.inputs_digest(root))
    if image == "runner":
        return runner
    return editor_plan.plan(pins, editor_plan.load(root), runner, editor_plan.inputs_digest(root))


def tag_for(image: str, profile: str, base: str, names, arch: str, inputs: str) -> str:
    """`<repository>-<profile>:<set>-<arch>-<digest>`; the digest folds the base's tag and the profile's inputs."""
    digest = hashlib.sha256(f"profile\0{profile}\0{base}\0{inputs}".encode()).hexdigest()
    label = "-".join(names) if names else "none"
    repository = {"runner": runner_plan.REPOSITORY, "editor": editor_plan.REPOSITORY}[image]
    return f"{repository}-{profile}:{label}-{arch}-{digest[:12]}"


def plan(root: Path, name: str, image: str, names, platform: str) -> Plan:
    """The profile's build for `image` over the declared set, or `Refused`."""
    if image not in IMAGES:
        raise Refused(f"the image is one of {list(IMAGES)}")
    profile = load(root, name)
    if image not in profile["images"]:
        raise Refused(f"profile {name!r} is not built for {image}")
    names = list(names) or list(profile["layers_on"])
    missing = [need for need in profile["layers_on"] if need not in names]
    if missing:
        raise Refused(f"profile {name!r} layers on {profile['layers_on']}; declare {missing} as well")
    base = base_plan(root, image, names, platform)
    adds = "\n".join(f"{e['id']}|{e['coordinates'] if 'coordinates' in e else PROJECT + ':' + e['path']}|{e['sha256']}"
                     for e in profile["adds"])
    paths = tuple(e["path"] for e in projects(profile))
    for e in projects(profile):
        project_dir(root, name, e)
    tag = tag_for(image, name, base.tag, base.names, base.arch, inputs_digest(root, name))
    args = {"PROFILE_NAME": name, "PROFILE_ADDS": adds, "BASE_IMAGE": base.tag, "PROFILE_PROJECTS": " ".join(paths)}
    published = f"{PUBLISHED[image]}-{name}"
    return Plan(name, image, base.names, base.arch, base.platform, tag, base.tag, published, args, paths)


def base_reference(built: Plan, base_digest: str) -> str:
    """The `FROM` value: the base's tag AND its digest. A build never starts from a tag alone."""
    if not _DIGEST.match(base_digest or ""):
        raise Refused("the base is named by its sha256 image digest: --base-digest sha256:<64 hex>")
    return f"{built.base_tag}@{base_digest}"
