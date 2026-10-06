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
* `editor-extension`: `{"kind": "editor-extension", "id": ..., "url": ..., "sha256": ...,
  "images": ["editor"], "settings": {...}}`. A zip or `.tar.gz` archive an editor extension needs
  and would otherwise download from the network at first use (the Kotlin language server is the
  first). `url` is an exact, versioned address and `sha256` the checksum of the archive, checked
  in the recipe's fetch stage (`fetch_extension.py`), which refuses a wrong archive naming the
  entry. The archive is unpacked to `/opt/profile/editor-extensions/<id>/`, without its first
  `strip` path components, in the images the entry NAMES
  (`images`, a subset of the profile's) and in no other. `platform` (optional, `linux/amd64`) names
  the only platform an archive of machine code is for: a build for another is refused by name.
  `patches` (optional) are exact-string edits of a file the extension installed in the base image,
  each `{"file", "sha256" (before), "after" (sha256 after), "replace": [[old, new], ...]}`,
  applied by `apply_patches.pl`, which refuses by name a file that is not the one pinned. `settings` are written as one
  `// @runtime kotlin` block into the editor's settings SEED, so a set without the profile has
  neither the archive nor the setting. The editor's own recipe, `editor-pins.json` and every base
  tag stay byte-identical: the editor's inputs are hashed into its tag, a profile's are not.

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
EXTENSION = "editor-extension"
#: Where an `editor-extension` archive is unpacked, one directory per entry id.
EXTENSION_ROOT = "/opt/profile/editor-extensions"
#: The settings seed block an `editor-extension` entry's `settings` are written into.
SEED_BLOCK = "kotlin"
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
            or PLACEHOLDER in entry.get("url", "")
            or not _SHA256.match(entry.get("sha256", ""))]


def projects(profile: dict) -> list[dict]:
    """The profile's `project` entries, in file order."""
    return [entry for entry in profile["adds"] if entry.get("kind") == PROJECT]


def extensions(profile: dict, image: str | None = None) -> list[dict]:
    """The profile's `editor-extension` entries, in file order; with `image`, only those it names."""
    return [entry for entry in profile["adds"] if entry.get("kind") == EXTENSION
            and (image is None or image in entry.get("images", []))]


def check_extensions(name: str, profile: dict, platform: str | None = None) -> None:
    """Refuse, by entry name, an `editor-extension` that cannot be installed as it is declared."""
    for entry in profile["adds"]:
        if entry.get("kind") != EXTENSION:
            continue
        label = f"profile {name!r} editor-extension {entry.get('id')!r}"
        if not runner_plan.NAME.match(entry.get("id") or ""):
            raise Refused(f"{label}: the id is a runtime-id-shaped word, the directory the archive is unpacked to")
        images = entry.get("images")
        if not images or not set(images) <= set(profile["images"]):
            raise Refused(f"{label}: images {images!r} must name one or more of the profile's images {profile['images']}")
        if not str(entry.get("url", "")).startswith(("https://", "file://")):
            raise Refused(f"{label}: url {entry.get('url')!r} is an https address of a versioned archive")
        if not isinstance(entry.get("settings", {}), dict):
            raise Refused(f"{label}: settings is a mapping of setting names to values")
        if platform and entry.get("platform") not in (None, platform):
            raise Refused(f"{label}: the archive is for {entry['platform']}, and this build is for {platform}")
        if not isinstance(entry.get("strip", 0), int) or entry.get("strip", 0) < 0:
            raise Refused(f"{label}: strip is a number of leading path components, zero or more")
        for patch in entry.get("patches", []):
            texts = [t for pair in patch.get("replace", []) for t in pair]
            if (not str(patch.get("file", "")).startswith("/opt/code-server/extensions/")
                    or not _SHA256.match(patch.get("sha256", "")) or not _SHA256.match(patch.get("after", ""))
                    or not texts or len(texts) % 2 or any("|" in t or "\n" in t for t in texts)):
                raise Refused(f"{label}: a patch names a file under /opt/code-server/extensions/, its sha256 before and "
                              f"after, and replacements without a '|' or a newline")


def patch_lines(profile: dict, image: str) -> str:
    """One `file|before|after|old|new...` line per patch of the image's extensions, for `apply_patches.pl`."""
    return "\n".join("|".join([patch["file"], patch["sha256"], patch["after"], *[t for pair in patch["replace"] for t in pair]])
                     for entry in extensions(profile, image) for patch in entry.get("patches", []))


def seed_block(profile: dict, image: str) -> str:
    """The `// @runtime kotlin` block the editor's settings seed gets: every `settings` of the image's extensions."""
    members = []
    for entry in extensions(profile, image):
        members += [f"    {json.dumps(key)}: {json.dumps(value)}," for key, value in entry.get("settings", {}).items()]
    if not members:
        return ""
    return "\n".join([f"    // @runtime {SEED_BLOCK}", *members, f"    // @end {SEED_BLOCK}"])


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


def _what(entry: dict) -> str:
    """What an entry adds, as the `PROFILE_ADDS` label line names it."""
    if "coordinates" in entry:
        return entry["coordinates"]
    if entry.get("kind") == EXTENSION:
        return f"{EXTENSION}:{entry['url']}"
    return f"{PROJECT}:{entry['path']}"


def fetch_image(root: Path, names, platform: str) -> str:
    """The pinned image the recipe's fetch stage runs in: the editor's own, named by `pins.json`."""
    pins = runner_plan.load(root)
    runner = runner_plan.plan(pins, editor_plan.selection(pins, names), platform, runner_plan.inputs_digest(root))
    return runner.build_args["UNPACK_IMAGE"]


def base_user(root: Path, image: str) -> str:
    """The user the base image runs as, which the profile's root-only steps hand back: read from the base's recipe."""
    if image == "runner":
        return "root"
    users = re.findall(r"^USER\s+(\S+)\s*$", (Path(root) / "docker" / "editor" / "Dockerfile").read_text(encoding="utf-8"), re.M)
    return users[-1]


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
    check_extensions(name, profile, platform)
    adds = "\n".join(f"{e['id']}|{_what(e)}|{e['sha256']}" for e in profile["adds"])
    fetch = "\n".join(f"{e['id']}|{e['url']}|{e['sha256']}|{e.get('strip', 0)}" for e in extensions(profile, image))
    paths = tuple(e["path"] for e in projects(profile))
    for e in projects(profile):
        project_dir(root, name, e)
    tag = tag_for(image, name, base.tag, base.names, base.arch, inputs_digest(root, name))
    args = {"PROFILE_NAME": name, "PROFILE_ADDS": adds, "BASE_IMAGE": base.tag, "PROFILE_PROJECTS": " ".join(paths),
            "PROFILE_EXTENSIONS": fetch, "PROFILE_SEED": seed_block(profile, image), "PROFILE_PATCHES": patch_lines(profile, image),
            "FETCH_IMAGE": fetch_image(root, names, platform), "PROFILE_RESTORE_USER": base_user(root, image)}
    published = f"{PUBLISHED[image]}-{name}"
    return Plan(name, image, base.names, base.arch, base.platform, tag, base.tag, published, args, paths)


def base_reference(built: Plan, base_digest: str) -> str:
    """The `FROM` value: the base's tag AND its digest. A build never starts from a tag alone."""
    if not _DIGEST.match(base_digest or ""):
        raise Refused("the base is named by its sha256 image digest: --base-digest sha256:<64 hex>")
    return f"{built.base_tag}@{base_digest}"
