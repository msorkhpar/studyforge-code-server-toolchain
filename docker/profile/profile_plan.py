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
            if PLACEHOLDER in entry["coordinates"] or not _SHA256.match(entry.get("sha256", ""))]


def inputs_digest(root: Path, name: str) -> str:
    """sha256 over the profile's file and `docker/profile/`: relative path and bytes, sorted."""
    root = Path(root)
    path = profile_path(root, name)
    files = [path] + sorted(p for p in (root / RECIPE).rglob("*") if p.is_file())
    digest = hashlib.sha256()
    for file in sorted(files, key=lambda p: p.relative_to(root).as_posix()):
        if "__pycache__" in file.parts:
            continue
        digest.update(file.relative_to(root).as_posix().encode() + b"\0" + file.read_bytes() + b"\0")
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
    adds = "\n".join(f"{e['id']}|{e['coordinates']}|{e['sha256']}" for e in profile["adds"])
    tag = tag_for(image, name, base.tag, base.names, base.arch, inputs_digest(root, name))
    args = {"PROFILE_NAME": name, "PROFILE_ADDS": adds, "BASE_IMAGE": base.tag}
    published = f"{PUBLISHED[image]}-{name}"
    return Plan(name, image, base.names, base.arch, base.platform, tag, base.tag, published, args)


def base_reference(built: Plan, base_digest: str) -> str:
    """The `FROM` value: the base's tag AND its digest. A build never starts from a tag alone."""
    if not _DIGEST.match(base_digest or ""):
        raise Refused("the base is named by its sha256 image digest: --base-digest sha256:<64 hex>")
    return f"{built.base_tag}@{base_digest}"
