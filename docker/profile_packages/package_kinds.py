"""The profile entry kinds `python-wheels` and `npm-packages`: checks, tag and plan — pure, no Docker.

**What it is.** Two entry kinds a profile may carry beside `project`, `dependency` and
`editor-extension`: pinned Python wheels installed offline with `pip install --no-index`, and a
pinned npm lockfile installed offline with `npm ci --offline`. Both are built by a second recipe,
`docker/profile_packages/Dockerfile`, layered on the image `docker/profile/Dockerfile` builds.

## ⭐ Why a separate directory
`docker/profile/` is an input of EVERY profile's tag. A byte changed there moves the tag of
`jvm-frameworks`, `fixture-libs` and `kotlin-editor`, so this layer lives beside it: that
directory, the planner and the recipe are untouched, and a profile with no entry of these kinds
has exactly the tag the profile planner computes. A profile that has one gets its own tag from
this module, which folds the profile planner's inputs, this directory and the entries' files.

⛔ So a profile with such an entry is planned and built through `docker/profile_packages/package_build.py`,
not `docker/profile/profile_build.py`, whose tag would not name the packages.

## The entries
* `python-wheels`: `{"kind", "id", "coordinates", "requirements", "sha256", "platforms",
  "imports"?, "remove_files"?, "allow_sdist"?}`. `coordinates` is a one-line label (the profile
  planner reads it). `requirements` is a file under `profiles/<name>/` of `name==version` lines, each
  with one or more `--hash=sha256:<64 hex>`, every dependency listed, no range; `sha256` is that
  file's digest; `platforms` lists the `linux/amd64` / `linux/arm64` builds the hashes cover.
  `imports` (optional) are modules the build proves import offline. `remove_files` (optional) are
  paths under the install's `site-packages` deleted after the hashed install, each of which must exist
  (the declared omit flag: the wheel's own hash stays the pin). `allow_sdist` (optional) is a reason;
  without it a source distribution is refused.
* `npm-packages`: `{"kind", "id", "path", "sha256", "omit_optional"?}`. `path` is a directory under
  `profiles/<name>/` with `package.json` and `package-lock.json`, every package with an
  `integrity`; `sha256` is the lockfile's digest; `omit_optional` (default false) skips optional
  dependencies, such as a platform binary.

**Depends on.** `docker/profile/profile_plan.py`, read-only.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPONENT = HERE.parents[1]
sys.path.insert(0, str(COMPONENT / "docker" / "profile"))
import profile_plan  # noqa: E402

Refused = profile_plan.Refused

RECIPE = "docker/profile_packages"
DOCKERFILE = f"{RECIPE}/Dockerfile"
WHEELS = "python-wheels"
NPM = "npm-packages"
PLATFORMS = ("linux/amd64", "linux/arm64")
LOCKFILE = "package-lock.json"
MANIFEST = "package.json"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HASH = re.compile(r"^--hash=sha256:[0-9a-f]{64}$")
_PIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,._-]+\])?==[A-Za-z0-9][A-Za-z0-9._+!-]*$")
_FILE = re.compile(r"^[A-Za-z0-9._@/+-]+$")
_MODULE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


@dataclass(frozen=True)
class Plan:
    """The profile planner's plan for a profile with package entries: `base` builds first, then `tag`."""
    profile: str
    image: str
    tag: str
    base: profile_plan.Plan
    build_args: dict[str, str]


def wheels(profile: dict) -> list[dict]:
    return [e for e in profile["adds"] if e.get("kind") == WHEELS]


def npm(profile: dict) -> list[dict]:
    return [e for e in profile["adds"] if e.get("kind") == NPM]


def has_packages(profile: dict) -> bool:
    return bool(wheels(profile) or npm(profile))


def has_legacy_entries(profile: dict) -> bool:
    """True when an entry of another kind (`project`, `editor-extension`...) needs the profile recipe's layer first."""
    return any(e.get("kind") not in (WHEELS, NPM) for e in profile["adds"])


def _file(root: Path, name: str, entry: dict, field: str) -> Path:
    """The entry's file under `profiles/<name>/`; a path that is not a plain relative one is refused by name."""
    where = str(entry.get(field, ""))
    parts = Path(where).parts
    label = f"profile {name!r} {entry.get('kind')} {entry.get('id')!r}"
    if not where or Path(where).is_absolute() or ".." in parts or "\\" in where or not _FILE.match(where):
        raise Refused(f"{label}: {field} {where!r} is not a plain relative path under profiles/{name}/")
    return Path(root) / profile_plan.PROFILES_DIR / name / where


def _lenient(root: Path, name: str, entry: dict, field: str) -> Path:
    try:
        return _file(root, name, entry, field)
    except Refused:
        return Path(root) / "no-such-file"


def _logical_lines(text: str):
    """Requirement lines with backslash continuations joined, comments and blanks dropped."""
    joined, pending = [], ""
    for raw in text.splitlines():
        line = raw.strip()
        if not pending and (not line or line.startswith("#")):
            continue
        if line.endswith("\\"):
            pending += line[:-1].strip() + " "
            continue
        joined.append((pending + line).strip())
        pending = ""
    if pending.strip():
        joined.append(pending.strip())
    return joined


def check_requirements(label: str, where: str, text: str) -> None:
    """Refuse, naming the file and the line, a requirements file with an unpinned or unhashed line."""
    lines = _logical_lines(text)
    if not lines:
        raise Refused(f"{label}: {where} lists no requirement")
    for line in lines:
        tokens = line.split()
        spec = tokens[0]
        if spec.startswith("-"):
            raise Refused(f"{label}: {where}: {line!r} is an option; a pin is `name==version --hash=sha256:...`")
        if not _PIN.match(spec):
            raise Refused(f"{label}: {where}: {spec!r} is not an exact `name==version` pin (no range, no URL)")
        hashes = tokens[1:]
        if not hashes or not all(_HASH.match(t) for t in hashes):
            raise Refused(f"{label}: {where}: {spec!r} has no `--hash=sha256:<64 hex>` (every line is hashed)")


def check_wheels(root: Path, name: str, profile: dict, platform: str | None = None) -> None:
    """Refuse, by entry and file name, a `python-wheels` entry that cannot be installed as declared."""
    for entry in wheels(profile):
        label = f"profile {name!r} python-wheels {entry.get('id')!r}"
        if not profile_plan.runner_plan.NAME.match(entry.get("id") or ""):
            raise Refused(f"{label}: the id is a runtime-id-shaped word")
        if not str(entry.get("coordinates", "")).strip():
            raise Refused(f"{label}: coordinates is a one-line label of what the requirements pin")
        platforms = entry.get("platforms")
        if not platforms or not set(platforms) <= set(PLATFORMS):
            raise Refused(f"{label}: platforms {platforms!r} must name one or more of {list(PLATFORMS)}")
        if platform and platform not in platforms:
            raise Refused(f"{label}: the hashes cover {platforms}, and this build is for {platform}")
        path = _file(root, name, entry, "requirements")
        shown = path.relative_to(root).as_posix()
        if not path.is_file():
            raise Refused(f"{label}: {shown} is missing")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != entry.get("sha256"):
            raise Refused(f"{label}: {shown} has sha256 {actual}, but the profile pins {entry.get('sha256')}")
        check_requirements(label, shown, path.read_text(encoding="utf-8"))
        for module in entry.get("imports", []):
            if not _MODULE.match(str(module)):
                raise Refused(f"{label}: imports names {module!r}, which is not a module name")
        for rel in entry.get("remove_files", []):
            parts = Path(str(rel)).parts
            if not rel or Path(rel).is_absolute() or ".." in parts or not _FILE.match(rel) or "," in rel:
                raise Refused(f"{label}: remove_files names {rel!r}, which is not a relative path under site-packages")
        if "allow_sdist" in entry and not (isinstance(entry["allow_sdist"], str) and entry["allow_sdist"].strip()):
            raise Refused(f"{label}: allow_sdist is a reason, a non-empty sentence; a source distribution is otherwise refused")


def check_lockfile(label: str, where: str, lock: dict) -> None:
    packages = lock.get("packages")
    if not isinstance(packages, dict) or lock.get("lockfileVersion", 0) < 2:
        raise Refused(f"{label}: {where} has no `packages` table (lockfileVersion 2 or 3)")
    for key, value in packages.items():
        if key == "" or value.get("link"):
            continue
        if not str(value.get("integrity", "")).startswith(("sha512-", "sha256-", "sha384-", "sha1-")):
            raise Refused(f"{label}: {where}: {key!r} has no `integrity` (every package is pinned by its hash)")
        if not value.get("version"):
            raise Refused(f"{label}: {where}: {key!r} has no exact version")


def check_npm(root: Path, name: str, profile: dict) -> None:
    """Refuse, by entry and file name, an `npm-packages` entry whose directory or lockfile does not match its pin."""
    for entry in npm(profile):
        label = f"profile {name!r} npm-packages {entry.get('id')!r}"
        if not profile_plan.runner_plan.NAME.match(entry.get("id") or ""):
            raise Refused(f"{label}: the id is a runtime-id-shaped word")
        if not isinstance(entry.get("omit_optional", False), bool):
            raise Refused(f"{label}: omit_optional is true or false")
        directory = _file(root, name, entry, "path")
        if not directory.is_dir():
            raise Refused(f"{label}: {directory.relative_to(root).as_posix()} is not a directory")
        for needed in (MANIFEST, LOCKFILE):
            if not (directory / needed).is_file():
                raise Refused(f"{label}: {(directory / needed).relative_to(root).as_posix()} is missing")
        lock = directory / LOCKFILE
        shown = lock.relative_to(root).as_posix()
        actual = hashlib.sha256(lock.read_bytes()).hexdigest()
        if actual != entry.get("sha256"):
            raise Refused(f"{label}: {shown} has sha256 {actual}, but the profile pins {entry.get('sha256')}")
        try:
            data = json.loads(lock.read_text(encoding="utf-8"))
        except ValueError as error:
            raise Refused(f"{label}: {shown} is not JSON: {error}") from None
        check_lockfile(label, shown, data)


def check(root: Path, name: str, profile: dict, platform: str | None = None) -> None:
    """Every refusal of both kinds, before Docker starts. A placeholder is refused by entry name."""
    for entry in wheels(profile) + npm(profile):
        for field in ("requirements", "path"):
            if profile_plan.PLACEHOLDER in str(entry.get(field, "")):
                raise Refused(f"profile {name!r} {entry['kind']} {entry['id']!r} still reads {profile_plan.PLACEHOLDER}")
    check_wheels(root, name, profile, platform)
    check_npm(root, name, profile)


def recipe_digest(root: Path, name: str, profile: dict) -> str:
    """sha256 over this recipe directory and the files of the profile's package entries."""
    root = Path(root)
    files = sorted(p for p in (root / RECIPE).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    # An entry still reading TO-BE-PINNED (a stub) has no file yet; it plans, and a build refuses it.
    for entry in wheels(profile):
        files.append(_lenient(root, name, entry, "requirements"))
    for entry in npm(profile):
        directory = _lenient(root, name, entry, "path")
        files += [directory / MANIFEST, directory / LOCKFILE]
    files = [f for f in files if f.is_file()]
    digest = hashlib.sha256()
    profile_plan._fold(digest, root, files)
    return digest.hexdigest()


def tag(root: Path, name: str, image: str, base: profile_plan.Plan, profile: dict) -> str:
    """The profile planner's own tag when there is no package entry, else one that also folds this layer."""
    if not has_packages(profile):
        return base.tag
    inputs = hashlib.sha256(f"{profile_plan.inputs_digest(root, name)}\0{recipe_digest(root, name, profile)}".encode()).hexdigest()
    return profile_plan.tag_for(image, name, base.base_tag, base.names, base.arch, inputs)


def _flag(value) -> str:
    return "1" if value else "0"


def build_args(profile: dict, base: profile_plan.Plan) -> dict[str, str]:
    lines = ["|".join([e["id"], e.get("requirements", ""), ",".join(e.get("imports", [])), ",".join(e.get("remove_files", [])),
                        _flag("allow_sdist" in e)]) for e in wheels(profile)]
    packages = ["|".join([e["id"], e.get("path", ""), _flag(e.get("omit_optional", False))]) for e in npm(profile)]
    return {"PROFILE_WHEELS": "\n".join(lines), "PROFILE_NPM": "\n".join(packages), "PROFILE_HAS_NPM": _flag(packages),
            "PROFILE_RESTORE_USER": base.build_args["PROFILE_RESTORE_USER"]}


def plan(root: Path, name: str, image: str, names, platform: str) -> Plan:
    """The two-step build: `base` (the profile planner's plan, built first) and the final `tag`."""
    root = Path(root)
    base = profile_plan.plan(root, name, image, names, platform)
    profile = profile_plan.load(root, name)
    return Plan(name, image, tag(root, name, image, base, profile), base, build_args(profile, base))
