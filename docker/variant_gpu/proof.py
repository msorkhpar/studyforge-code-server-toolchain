"""The variant's build-time proof, with NO network and NO GPU: what a CPU can check of a CUDA build.

    python3 proof.py <venv>

1. highspy is the CUDA build (`_core` links libcudalin; its version is the profile's own) and every shared
   library it needs resolves (`ldd` shows no `not found`).
2. It solves an LP with the simplex method to the value the profile's highspy gives (a known optimum).
3. It loads beside OR-Tools in ONE process, in both import orders, and both solve: the conflict that holds
   highspy 1.15 out of the profile (undefined symbols) must not be here. Each order runs in its own process.
4. What a GPU-built PDLP does with no GPU is RECORDED, not required: it runs in a child process.
"""

from __future__ import annotations

import glob
import os
import subprocess
import sys

VENV = sys.argv[1]

LP = """
import highspy
h = highspy.Highs()
h.setOptionValue("output_flag", False)
h.setOptionValue("solver", "{solver}")
inf = highspy.kHighsInf
# max 3x + 2y  s.t.  x + y <= 4,  x + 3y <= 6,  x <= 3,  x, y >= 0  -> x = 3, y = 1, objective 11
h.addVars(2, [0.0, 0.0], [inf, inf])
h.changeColsCost(2, [0, 1], [3.0, 2.0])
h.changeObjectiveSense(highspy.ObjSense.kMaximize)
h.addRow(-inf, 4.0, 2, [0, 1], [1.0, 1.0])
h.addRow(-inf, 6.0, 2, [0, 1], [1.0, 3.0])
h.changeColBounds(0, 0.0, 3.0)
h.run()
print(h.modelStatusToString(h.getModelStatus()), round(h.getInfo().objective_function_value, 9))
"""

ORTOOLS = """
from ortools.math_opt.python import mathopt
m = mathopt.Model()
x = m.add_variable(lb=0, ub=3); y = m.add_variable(lb=0)
m.add_linear_constraint(x + y <= 4); m.add_linear_constraint(x + 3 * y <= 6)
m.maximize(3 * x + 2 * y)
print("ortools-highs", round(mathopt.solve(m, mathopt.SolverType.HIGHS).objective_value(), 9))
"""


def run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)


def must(code: str, expect: str, what: str, also: str = "") -> None:
    done = run(code)
    if done.returncode != 0 or expect not in done.stdout or also not in done.stdout:
        sys.stderr.write(done.stdout + done.stderr)
        raise SystemExit(f"proof: {what}: exit {done.returncode}, expected {expect!r}")
    print(f"proof: {what}: {done.stdout.strip().splitlines()[-1]}")


def main() -> int:
    import highspy

    here = os.path.dirname(highspy.__file__)
    if not os.path.isfile(os.path.join(here, "libcudalin.so")):
        raise SystemExit("proof: the installed highspy is not the CUDA build (no libcudalin beside the module)")
    for library in glob.glob(os.path.join(here, "_core*.so")) + glob.glob(os.path.join(here, "libcudalin.so")):
        ldd = subprocess.run(["ldd", library], capture_output=True, text=True).stdout
        if "not found" in ldd:
            raise SystemExit(f"proof: {library} has an unresolved library:\n{ldd}")
        cuda = sorted({line.split()[0] for line in ldd.splitlines() if line.split() and "cu" in line.split()[0]})
        print(f"proof: {os.path.basename(library)} resolves every library; CUDA ones: {cuda}")
    must(LP.format(solver="simplex"), "Optimal 11.0", "highspy (CUDA build), simplex")
    must(LP.format(solver="ipm"), "Optimal 11.0", "highspy (CUDA build), interior point")
    must("import highspy\n" + ORTOOLS + LP.format(solver="simplex"), "Optimal 11.0", "highspy, then OR-Tools, one process", "ortools-highs 11.0")
    must(ORTOOLS + LP.format(solver="simplex"), "Optimal 11.0", "OR-Tools, then highspy, one process", "ortools-highs 11.0")
    pdlp = run(LP.format(solver="pdlp"))
    tail = (pdlp.stdout + pdlp.stderr).strip().splitlines()[-1:] or [""]
    print(f"record: PDLP in the CUDA build with no GPU: exit {pdlp.returncode}, {tail[0][:200]!r}")
    print(f"record: the cuOpt venv is {VENV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
