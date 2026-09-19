"""The editor image's build plan — pure, no I/O beyond reading files.

**What it does.** Turns the editor's runtime set, a platform and the runner's
own plan into the exact `docker build` arguments and the editor's tag, refusing
before Docker starts anything `editor-pins.json` does not pin. It also carries
the editor's own static checks.

**How you use it.** `load(root)` reads `editor-pins.json`; `plan(pins,
editor_pins, runner, digest)` returns an `EditorPlan` or raises `Refused`
(the runner's own refusal class); `inputs_digest(root)` names the build's
inputs; `pins_findings` and `install_findings` return what is wrong, empty when
nothing is.

**Depends on.** The standard library, and `docker/minimal/plan.py`, whose
functions are reused unchanged.

## Why the runner's plan is an input
⭐ The editor chooses NO runtime version (register ruling, PO round 122): it
copies every runtime out of the runner image built for the same set, so
`pins.json` stays the one place a runtime version is chosen. The runner's
checks, its `/opt` expectation and its tag are therefore read from the
runner's `Plan`, never re-derived here.

## The seam to TC-02
In `TC-01` the set is the constant `EDITOR_SET` and the extensions it requires
are the constant `REQUIRED_EXTENSIONS`. Turning both into functions of a
corpus's declared runtimes is `TC-02`'s work.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "minimal"))
import plan as runner_plan  # noqa: E402

Refused = runner_plan.Refused
EDITOR_PINS = "editor-pins.json"
DOCKERFILE = "docker/editor/Dockerfile"
#: The editor's own inputs. The runner's digest is folded in as well, so the
#: editor's tag moves whenever the runner's does — and `docker/minimal/` is
#: not touched, so no runner tag moves because the editor exists.
OWN_INPUTS = (EDITOR_PINS, "docker/editor")
REPOSITORY = "code-server-toolchain/editor"
#: The extraction source's five toolchains. TC-02 turns this into a selection.
EDITOR_SET = ("gradle", "java", "kotlin", "node", "python")
#: What the editor needs for EDITOR_SET: the extraction source's list. Removing
#: one of these from editor-pins.json is refused before Docker starts.
REQUIRED_EXTENSIONS = (
    "fwcd.kotlin", "ms-python.debugpy", "ms-python.python", "redhat.java",
    "vscjava.vscode-gradle", "vscjava.vscode-java-debug", "vscjava.vscode-java-test",
)
#: The Open VSX target platform for each architecture pins.json names.
TARGETS = {"amd64": "linux-x64", "arm64": "linux-arm64"}

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class EditorPlan:
    names: tuple[str, ...]
    arch: str
    platform: str
    tag: str
    build_args: dict[str, str]


def load(root: Path) -> dict:
    return json.loads((Path(root) / EDITOR_PINS).read_text(encoding="utf-8"))


def inputs_digest(root: Path) -> str:
    """sha256 over the runner's inputs digest, then every editor input file (R10)."""
    root = Path(root)
    digest = hashlib.sha256(b"runner\0" + runner_plan.inputs_digest(root).encode() + b"\0")
    files: list[Path] = []
    for entry in OWN_INPUTS:
        path = root / entry
        files.extend([path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file()))
    for path in sorted(files, key=lambda p: p.relative_to(root).as_posix()):
        if "__pycache__" in path.parts:
            continue
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def plan(pins: dict, editor_pins: dict, runner: runner_plan.Plan, digest: str) -> EditorPlan:
    """Return the editor build for the runner's set and platform, or raise `Refused`."""
    declared, arch = runner.names, runner.arch
    extensions = editor_pins["extensions"]
    missing = [ext for ext in REQUIRED_EXTENSIONS if ext not in extensions]
    if missing:
        raise Refused(f"the editor requires extension(s) {missing}, which editor-pins.json does not pin")
    for ext, entry in sorted(extensions.items()):
        unpinned = [d for d in entry["depends"] if d not in extensions]
        unpinned += [p for p in entry["pack"] if p not in extensions and p not in entry.get("pack_absent", {})]
        if unpinned:
            raise Refused(f"'{ext}' needs {unpinned}; pin each, or record why a pack member is absent")
    fetch = [f"{ext}-{entry['version']}.vsix|{_file(ext, entry, arch)['url']}|{_file(ext, entry, arch)['sha256']}"
             for ext, entry in sorted(extensions.items())]
    typescript = editor_pins["typescript"]
    with_typescript = typescript["for"] in declared
    if with_typescript:
        fetch.append(f"typescript.tgz|{typescript['url']}|{typescript['sha256']}")
    readline = editor_pins["readline"]
    checks = runner.build_args["CHECKS"].splitlines()
    if with_typescript:
        checks += [f"typescript|{c['command']}|{c['expect'].format(version=typescript['version'])}"
                   for c in typescript["checks"]]
    args = {
        "RUNNER_IMAGE": runner.tag,
        "EDITOR_BASE": f"{editor_pins['base']['image']}@{editor_pins['base']['digest']}",
        # A build tool only: the pinned Python image runs fetch.py. It reaches
        # the editor only through the runner, when python is declared.
        "FETCH_IMAGE": runner.build_args["UNPACK_IMAGE"],
        "FETCH": "\n".join(fetch),
        "EXPECTED_EXTENSIONS": " ".join(f"{ext}@{extensions[ext]['version']}" for ext in sorted(extensions)),
        "WITH_TYPESCRIPT": "yes" if with_typescript else "no",
        "WITH_READLINE": "yes" if readline["for"] in declared else "no",
        "READLINE_SNAPSHOT": readline["snapshot"],
        "READLINE_PACKAGES": " ".join(f"{k}={v}" for k, v in sorted(readline["packages"].items())),
        "CHECKS": "\n".join(checks),
        "OPT_EXPECTED": " ".join(sorted(runner_plan.opt_dirs(declared) + ["code-server"])),
        "JAVA_RUNTIME": java_runtime(pins),
        "DECLARED": " ".join(declared),
    }
    tag = runner_plan.tag_for(declared, arch, digest).replace(runner_plan.REPOSITORY, REPOSITORY, 1)
    return EditorPlan(declared, arch, runner.platform, tag, args)


def java_runtime(pins: dict) -> str:
    """The execution-environment name the Java extension expects, from the pinned JDK.

    ⛔ Never written by hand: the extraction source's seed said `JavaSE-26`
    against a JDK pinned elsewhere, and the two disagreed (TC-01/5).
    """
    return f"JavaSE-{pins['runtimes']['java']['version'].split('.')[0]}"


def _file(ext: str, entry: dict, arch: str) -> dict:
    files = entry["files"]
    target = TARGETS.get(arch)
    if target in files:
        return files[target]
    if "universal" in files:
        return files["universal"]
    raise Refused(f"'{ext}' has no file pinned for {target}; pinned: {sorted(files)}")


def pins_findings(editor_pins: dict) -> list[str]:
    """What is wrong with the editor pins' shape, empty when nothing is."""
    found: list[str] = []
    entries = [("base", editor_pins["base"]), ("typescript", editor_pins["typescript"]),
               ("readline", editor_pins["readline"])] + sorted(editor_pins["extensions"].items())
    if not _DIGEST.match(editor_pins["base"].get("digest", "")):
        found.append("base: the image is pinned by a sha256 index digest")
    if not _SHA256.match(editor_pins["typescript"].get("sha256", "")):
        found.append("typescript: the tarball is pinned by a recorded sha256")
    if not editor_pins["typescript"].get("integrity", "").startswith("sha512-"):
        found.append("typescript: the registry's published integrity is recorded")
    for arch, debs in editor_pins["readline"]["debs"].items():
        if set(debs) != set(editor_pins["readline"]["packages"]) or not all(_SHA256.match(v) for v in debs.values()):
            found.append(f"readline ({arch}): every package has a recorded sha256")
    for ext, entry in sorted(editor_pins["extensions"].items()):
        for target, file in entry["files"].items():
            if not _SHA256.match(file.get("sha256", "")):
                found.append(f"{ext} ({target}): a .vsix is pinned by a recorded sha256")
            if f"/{entry['version']}/" not in file.get("url", ""):
                found.append(f"{ext} ({target}): the url names the pinned version")
    for label, entry in entries:
        if not entry.get("sources") or not all(s.get("host") and s.get("taken") for s in entry["sources"]):
            found.append(f"{label}: every pin records its source host and when it was taken")
        if not isinstance(entry.get("single_source"), bool):
            found.append(f"{label}: every pin says whether it is single-source")
        if entry.get("single_source") is True and not entry.get("why_single"):
            found.append(f"{label}: a single-source pin says why no second source exists")
    return found


_INSTALL = re.compile(r"--install-extension[=\s]+(?P<arg>\S+)")


def install_findings(text: str) -> list[str]:
    """Every `--install-extension` names a FILE, never a bare marketplace id."""
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        for match in _INSTALL.finditer(line):
            if not match.group("arg").strip("\"'").startswith(("/", "$")):
                found.append(f"line {number}: an extension is installed by id; install the pinned file")
    return found
