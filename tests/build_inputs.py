"""The build's inputs, copied ONCE for every test module that plants one.

⛔ `W391` (`TC-04/3`): every module that planted a defect kept its own copy of
this, so adding one top-level input directory — `lockdown/`, when TC-04 landed
it — meant the same edit in each of them, and a module that was missed built
against a context the real build does not have.

⭐ The entries are **derived** from the plans' own declarations,
`plan.INPUT_ROOTS` and `editor_plan.OWN_INPUTS`, and never listed a second
time here: a new input directory is ONE edit, in the plan that declares it,
and every planted copy carries it. `tests/test_build_inputs.py` asserts that
both ways.

⚠️ The entries are the TOP-LEVEL names those declarations reach — a copy of
`docker/editor` alone is not a build context — so `docker/minimal` and
`docker/editor` both resolve to `docker`, copied once.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docker" / "editor"))

import editor_plan  # noqa: E402

runner_plan = editor_plan.runner_plan

#: In no inputs digest — nothing the image carries depends on it — but the
#: build context is read through it, so a planted copy carries it too.
CONTEXT_ONLY = (".dockerignore",)


def declared() -> tuple[str, ...]:
    """Every input the two plans declare: the runner's, then the editor's own."""
    return tuple(runner_plan.INPUT_ROOTS) + tuple(editor_plan.OWN_INPUTS)


def entries(inputs=None) -> tuple[str, ...]:
    """The top-level names a copy carries, derived — never a second list.

    `inputs` is a plan's own declaration; the default is both plans' together.
    """
    inputs = declared() if inputs is None else inputs
    names: dict[str, None] = {}
    for entry in tuple(inputs) + CONTEXT_ONLY:
        names.setdefault(Path(entry).parts[0], None)
    return tuple(names)


def copy_inputs(target, source: Path = ROOT, inputs=None) -> Path:
    """A copy of the build's inputs at `target`, never touching the tree.

    `target` is replaced if it exists, so a caller hands over a temporary
    directory or a name under `.work/` and gets a clean context back.
    """
    target, source = Path(target), Path(source)
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    for entry in entries(inputs):
        path = source / entry
        if path.is_dir():
            shutil.copytree(path, target / entry, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy(path, target / entry)
    return target
