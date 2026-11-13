"""A GPU variant's plan, read from `variants/<name>.json` — pure, no Docker.

**What it is.** A variant is an image layered on a PROFILE image (not on a shared base): the profile's
own tag and digest are its `FROM`, and it adds what only a device-specific image may carry. The first is
`optimization-gpu`: HiGHS built with CUDA as highspy, and NVIDIA cuOpt in a venv of its own, on the
`optimization` profile's runner.

## ⭐ Why a directory of its own
`docker/profile/` and `docker/profile_packages/` are inputs of EVERY profile's tag, and `profiles/*.json`
is read by tests that plan every profile. A variant changes none of them: its file is
`variants/<name>.json`, its pinned files are under `variants/<name>/`, its recipe is this directory.
So adding or editing a variant moves no base tag and no profile tag; a change to the profile moves the
variant's tag, because the profile's tag is folded into it. `package_build.py --profile <variant>`
refuses (no such profile), so a variant is never planned as a profile by mistake.

## The tag
`<repository>-<variant>:<set>-<arch>-<12 hex>`, the 12 hex a digest of the variant's name, the PROFILE
image's tag and the variant's inputs: its file, every file under `variants/<name>/` and this directory.

## The entries
* `source-build` (`highspy-cuda`): a source archive by exact `url` and `sha256`, the `edits` file
  (`docker/variant_gpu/edit_source.py`) and the `build_requirements` it is built with, each pinned by its
  digest; `replaces` names the profile's wheel it is installed in place of.
* `venv-wheels`: a hashed requirements file installed, offline, into the variant's `venv`.

**Depends on.** `docker/profile_packages/package_kinds.py` and `docker/profile/profile_plan.py`, read-only.
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
sys.path.insert(0, str(COMPONENT / "docker" / "profile_packages"))
sys.path.insert(0, str(COMPONENT / "docker" / "profile"))
import package_kinds  # noqa: E402
import profile_plan  # noqa: E402

Refused = profile_plan.Refused

VARIANTS_DIR = "variants"
RECIPE = "docker/variant_gpu"
DOCKERFILE = f"{RECIPE}/Dockerfile"
SOURCE = "source-build"
VENV = "venv-wheels"
#: The published name: the profile's published name plus the variant's suffix.
PUBLISHED = profile_plan.PUBLISHED
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PACKAGE = re.compile(r"^[a-z0-9][a-z0-9+.-]*=[0-9][A-Za-z0-9.+:~-]*$")
_SNAPSHOT = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")
_ARCHS = re.compile(r"^[0-9]{2,3}(;[0-9]{2,3})*$")


@dataclass(frozen=True)
class Plan:
    variant: str
    image: str
    profile: str
    names: tuple[str, ...]
    arch: str
    platform: str
    tag: str
    profile_tag: str
    published: str
    build_args: dict[str, str]


def variant_path(root: Path, name: str) -> Path:
    if not profile_plan.runner_plan.NAME.match(name or ""):
        raise Refused("a variant name is a runtime-id-shaped word")
    return Path(root) / VARIANTS_DIR / f"{name}.json"


def known(root: Path) -> list[str]:
    return sorted(p.stem for p in (Path(root) / VARIANTS_DIR).glob("*.json"))


def load(root: Path, name: str) -> dict:
    path = variant_path(root, name)
    if not path.is_file():
        raise Refused(f"no variant {name!r}; the variants are {known(root)}")
    return json.loads(path.read_text(encoding="utf-8"))


def entries(variant: dict, kind: str) -> list[dict]:
    return [e for e in variant["adds"] if e.get("kind") == kind]


def _pinned(root: Path, name: str, label: str, where: str, digest: str) -> Path:
    """The file `variants/<name>/<where>`, which must exist and have the pinned sha256."""
    parts = Path(where).parts
    if not where or Path(where).is_absolute() or ".." in parts or "\\" in where:
        raise Refused(f"{label}: {where!r} is not a plain relative path under {VARIANTS_DIR}/{name}/")
    path = Path(root) / VARIANTS_DIR / name / where
    shown = path.relative_to(root).as_posix()
    if not path.is_file():
        raise Refused(f"{label}: {shown} is missing")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != digest:
        raise Refused(f"{label}: {shown} has sha256 {actual}, but the variant pins {digest}")
    return path


def requirement_names(text: str) -> dict[str, str]:
    """`{name: version}` of a hashed requirements file, names normalised."""
    pins = {}
    for line in package_kinds._logical_lines(text):
        spec = line.split()[0]
        name, version = spec.split("==")
        pins[re.sub(r"[-_.]+", "-", name).lower()] = version
    return pins


def check(root: Path, name: str, variant: dict, platform: str | None = None) -> None:
    """Every refusal, before Docker starts: a file or digest that is not the pinned one, an unhashed line,
    two requirement files that pin one package, a build tool that is not an exact version."""
    root = Path(root)
    if variant.get("variants_api") != 1 or variant.get("name") != name:
        raise Refused(f"variant {name!r}: variants_api is 1 and name is the file's own name")
    if variant.get("images") != ["runner"]:
        raise Refused(f"variant {name!r}: images is [\"runner\"]; a GPU editor is not built")
    if platform and platform != "linux/amd64":
        raise Refused(f"variant {name!r}: the CUDA wheels and the HiGHS build are pinned for linux/amd64, and this build is for {platform}")
    cuda = variant.get("cuda", {})
    if not _ARCHS.match(str(cuda.get("architectures", ""))):
        raise Refused(f"variant {name!r}: cuda.architectures is a list of compute capabilities, such as 75;80;86;120")
    if not str(variant.get("venv", "")).startswith("/opt/"):
        raise Refused(f"variant {name!r}: venv is a directory under /opt")
    tools = variant.get("build_tools", {})
    if not _SNAPSHOT.match(str(tools.get("snapshot", ""))):
        raise Refused(f"variant {name!r}: build_tools.snapshot is a snapshot.debian.org timestamp")
    for package in tools.get("packages", []):
        if not _PACKAGE.match(package):
            raise Refused(f"variant {name!r}: build tool {package!r} is not an exact `name=version`")
    if not isinstance(variant.get("build_jobs"), int) or not 1 <= variant["build_jobs"] <= 8:
        raise Refused(f"variant {name!r}: build_jobs is a number from 1 to 8 (a CUDA compile is heavy)")
    sources = entries(variant, SOURCE)
    if len(sources) != 1:
        raise Refused(f"variant {name!r}: one source-build entry, the HiGHS build")
    for entry in sources:
        label = f"variant {name!r} {SOURCE} {entry.get('id')!r}"
        if not str(entry.get("url", "")).startswith("https://") or not _SHA256.match(str(entry.get("sha256", ""))):
            raise Refused(f"{label}: url is an exact https address and sha256 its 64 hex digest")
        _pinned(root, name, label, entry.get("edits", ""), entry.get("edits_sha256", ""))
        build = _pinned(root, name, label, entry.get("build_requirements", ""), entry.get("build_requirements_sha256", ""))
        package_kinds.check_requirements(label, build.relative_to(root).as_posix(), build.read_text(encoding="utf-8"))
        if not re.match(r"^[a-z0-9-]+==[0-9][0-9.]*$", str(entry.get("replaces", ""))):
            raise Refused(f"{label}: replaces names the profile's wheel, `name==version`")
    seen: dict[str, str] = {}
    for entry in entries(variant, VENV):
        label = f"variant {name!r} {VENV} {entry.get('id')!r}"
        path = _pinned(root, name, label, entry.get("requirements", ""), entry.get("sha256", ""))
        text = path.read_text(encoding="utf-8")
        package_kinds.check_requirements(label, path.relative_to(root).as_posix(), text)
        for package in requirement_names(text):
            if package in seen:
                raise Refused(f"{label}: {package} is pinned again; {seen[package]} already pins it")
            seen[package] = entry["id"]
    unknown = [e.get("kind") for e in variant["adds"] if e.get("kind") not in (SOURCE, VENV)]
    if unknown:
        raise Refused(f"variant {name!r}: entry kinds {unknown} are not ones this recipe builds")


def inputs_digest(root: Path, name: str) -> str:
    """sha256 over the variant's file, every file under `variants/<name>/` and this recipe directory."""
    root = Path(root)
    files = [variant_path(root, name)]
    files += [p for p in (root / VARIANTS_DIR / name).rglob("*") if p.is_file()]
    files += [p for p in (root / RECIPE).rglob("*") if p.is_file()]
    digest = hashlib.sha256()
    profile_plan._fold(digest, root, files)
    return digest.hexdigest()


def tag_for(image: str, variant: str, profile_tag: str, names, arch: str, inputs: str) -> str:
    digest = hashlib.sha256(f"variant\0{variant}\0{profile_tag}\0{inputs}".encode()).hexdigest()
    label = "-".join(names) if names else "none"
    repository = profile_plan.runner_plan.REPOSITORY
    return f"{repository}-{variant}:{label}-{arch}-{digest[:12]}"


def build_args(root: Path, name: str, variant: dict, profile_tag: str) -> dict[str, str]:
    source = entries(variant, SOURCE)[0]
    venvs = entries(variant, VENV)
    return {
        "PROFILE_IMAGE": profile_tag,
        "VARIANT_NAME": name,
        "VARIANT_ADDS": "\n".join(f"{e['id']}|{e['coordinates']}" for e in variant["adds"]),
        "HIGHS_URL": source["url"],
        "HIGHS_SHA256": source["sha256"],
        "HIGHS_EDITS": source["edits"],
        "HIGHS_BUILD_REQUIREMENTS": source["build_requirements"],
        "HIGHS_REPLACES": source["replaces"],
        "CUDA_REQUIREMENTS": next(e["requirements"] for e in venvs if e["id"] == "cuda-toolkit"),
        "VENV_REQUIREMENTS": " ".join(e["requirements"] for e in venvs),
        "VENV_IMPORTS": ",".join(m for e in venvs for m in e.get("imports", [])),
        "VENV": variant["venv"],
        "CUDA_ARCHITECTURES": variant["cuda"]["architectures"],
        "BUILD_JOBS": str(variant["build_jobs"]),
        "APT_SNAPSHOT": variant["build_tools"]["snapshot"],
        "APT_PACKAGES": " ".join(variant["build_tools"]["packages"]),
    }


def plan(root: Path, name: str, image: str, names, platform: str) -> Plan:
    """The variant's build for `image` over the declared set, or `Refused`. The profile's plan is the one
    `package_build.py --print-tag` prints for the same set, so the CPU image a consumer already runs is
    exactly the image this one is layered on."""
    root = Path(root)
    variant = load(root, name)
    if image not in variant["images"]:
        raise Refused(f"variant {name!r} is not built for {image}")
    profile = package_kinds.plan(root, variant["layers_on_profile"], image, names, platform)
    tag = tag_for(image, name, profile.tag, profile.base.names, profile.base.arch, inputs_digest(root, name))
    args = build_args(root, name, variant, profile.tag)
    return Plan(name, image, variant["layers_on_profile"], profile.base.names, profile.base.arch, profile.base.platform,
                tag, profile.tag, f"{PUBLISHED[image]}-{name}", args)
