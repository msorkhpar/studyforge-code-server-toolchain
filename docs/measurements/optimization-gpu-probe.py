"""GPU probes of the optimization-gpu variant: HiGHS's GPU PDLP and cuOpt, each solve run twice.

    sh docs/measurements/optimization-gpu-probe.sh <gpu image>

Runs INSIDE the variant with `--gpus all --network none` (the .sh starts it). Prints one JSON object per
line: the device, then each solve with its status, objective, time, and whether the second run gave the
same bits (objective and every primal value compared as IEEE-754 bytes).

* HiGHS (the image's python3): a 2-variable LP and a generated transportation LP, solved by PDLP on the
  GPU (`solver="pdlp"`) and, for comparison, by the interior point method on the CPU. The CUDA build has no
  CPU PDLP, so OR-Tools' PDLP (CPU) is the PDLP-to-PDLP comparison.
* cuOpt (/opt/gpu/cuopt/bin/python, this file re-run with `cuopt`): the same small LP with cuOpt's default
  method and with PDLP, and a small MILP.
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import tempfile
import time

SEED = 20261112


def emit(**record) -> None:
    print(json.dumps(record), flush=True)


def bits(values) -> str:
    return struct.pack(f"<{len(values)}d", *values).hex()


def transport(m: int, n: int):
    """A balanced transportation LP: m sources, n sinks, integer costs 1..99 from a fixed-seed generator."""
    state = SEED
    costs = []
    for _ in range(m * n):
        state = (6364136223846793005 * state + 1442695040888963407) % 2**64
        costs.append(1 + (state >> 33) % 99)
    supply = [n * 10 + (i % 7) for i in range(m)]
    total = sum(supply)
    demand = [total // n + (1 if j < total % n else 0) for j in range(n)]
    return costs, supply, demand


# ------------------------------------------------------------------ HiGHS, in the image's python3
def highs_model(h, highspy, kind: str, size: int):
    inf = highspy.kHighsInf
    if kind == "small":
        h.addVars(2, [0.0, 0.0], [3.0, inf])
        h.changeColsCost(2, [0, 1], [-3.0, -2.0])          # max 3x + 2y as min -3x - 2y
        h.addRow(-inf, 4.0, 2, [0, 1], [1.0, 1.0])
        h.addRow(-inf, 6.0, 2, [0, 1], [1.0, 3.0])
        return
    costs, supply, demand = transport(size, size)
    count = size * size
    h.addVars(count, [0.0] * count, [inf] * count)
    h.changeColsCost(count, list(range(count)), [float(c) for c in costs])
    for i in range(size):
        h.addRow(-inf, float(supply[i]), size, [i * size + j for j in range(size)], [1.0] * size)
    for j in range(size):
        h.addRow(float(demand[j]), inf, size, [i * size + j for i in range(size)], [1.0] * size)


def highs_solve(kind: str, size: int, solver: str) -> dict:
    import highspy

    h = highspy.Highs()
    log = tempfile.NamedTemporaryFile(suffix=".log", delete=False).name
    h.setOptionValue("output_flag", True)
    h.setOptionValue("log_to_console", False)
    h.setOptionValue("log_file", log)
    h.setOptionValue("solver", solver)
    h.setOptionValue("random_seed", 0)
    highs_model(h, highspy, kind, size)
    start = time.perf_counter()
    h.run()
    seconds = time.perf_counter() - start
    info = h.getInfo()
    solution = h.getSolution()
    with open(log, encoding="utf-8", errors="replace") as handle:
        lines = [line.strip() for line in handle if any(k in line for k in ("GPU", "CUDA", "cuPDLP", "PDLP", "pdlp"))]
    os.unlink(log)
    return {"status": h.modelStatusToString(h.getModelStatus()), "objective": info.objective_function_value,
            "seconds": round(seconds, 4), "pdlp_iterations": info.pdlp_iteration_count,
            "objective_bits": bits([info.objective_function_value]), "x_bits_sha": _sha(bits(list(solution.col_value))),
            "log": lines[:6]}


def _sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()[:16]


def ortools_pdlp(size: int) -> dict:
    """OR-Tools' PDLP on the CPU, for a PDLP-to-PDLP comparison, in a child process of its own."""
    code = """
import json, sys, time
from ortools.math_opt.python import mathopt
costs, supply, demand = json.load(sys.stdin)
n = len(supply)
m = mathopt.Model()
x = [[m.add_variable(lb=0) for j in range(n)] for i in range(n)]
for i in range(n): m.add_linear_constraint(sum(x[i]) <= supply[i])
for j in range(n): m.add_linear_constraint(sum(x[i][j] for i in range(n)) >= demand[j])
m.minimize(sum(costs[i * n + j] * x[i][j] for i in range(n) for j in range(n)))
start = time.perf_counter()
r = mathopt.solve(m, mathopt.SolverType.PDLP)
print(json.dumps({"status": r.termination.reason.name, "objective": r.objective_value(),
                  "seconds": round(time.perf_counter() - start, 4)}))
"""
    done = subprocess.run([sys.executable, "-c", code], input=json.dumps(transport(size, size)), capture_output=True,
                          text=True, timeout=1800)
    return json.loads(done.stdout.strip().splitlines()[-1]) if done.returncode == 0 else {"error": done.stderr[-300:]}


def highs_probes(size: int) -> None:
    for kind, n in (("small", 0), ("transport", size)):
        cpu = highs_solve(kind, n, "ipm")
        first, second = highs_solve(kind, n, "pdlp"), highs_solve(kind, n, "pdlp")
        same = first["objective_bits"] == second["objective_bits"] and first["x_bits_sha"] == second["x_bits_sha"]
        gap = abs(first["objective"] - cpu["objective"]) / max(1.0, abs(cpu["objective"]))
        emit(probe=f"highs-{kind}", variables=(2 if kind == "small" else n * n), cpu_ipm=cpu, gpu_pdlp=first,
             gpu_pdlp_again={k: second[k] for k in ("status", "objective", "seconds", "pdlp_iterations")},
             repeat_bit_identical=same, relative_difference_to_cpu=gap)
        if kind == "transport":
            emit(probe=f"ortools-pdlp-cpu-{kind}", variables=n * n, result=ortools_pdlp(n))


# ------------------------------------------------------------------ cuOpt, in its own venv
def cuopt_probes() -> None:
    from cuopt.linear_programming import problem as cp
    from cuopt.linear_programming.solver_settings import SolverMethod, SolverSettings
    from cuopt.linear_programming.solver.solver_parameters import get_solver_parameter_names

    names = list(get_solver_parameter_names())
    emit(probe="cuopt-parameters", determinism_or_seed=[n for n in names if "determin" in n or "seed" in n])

    def lp(method):
        p = cp.Problem("small-lp")
        x = p.addVariable(lb=0.0, ub=3.0, name="x")
        y = p.addVariable(lb=0.0, name="y")
        p.addConstraint(x + y <= 4, name="a")
        p.addConstraint(x + 3 * y <= 6, name="b")
        p.setObjective(3 * x + 2 * y, sense=cp.MAXIMIZE)
        settings = SolverSettings()
        if method is not None:
            settings.set_parameter("method", method)
        p.solve(settings)
        return p, [x, y]

    def milp():
        p = cp.Problem("small-milp")
        v = [p.addVariable(lb=0.0, ub=10.0, vtype=cp.INTEGER, name=n) for n in "xyz"]
        p.addConstraint(2 * v[0] + 3 * v[1] + v[2] <= 5, name="r1")
        p.addConstraint(4 * v[0] + v[1] + 2 * v[2] <= 11, name="r2")
        p.addConstraint(3 * v[0] + 4 * v[1] + 2 * v[2] <= 8, name="r3")
        p.setObjective(5 * v[0] + 4 * v[1] + 3 * v[2], sense=cp.MAXIMIZE)
        settings = SolverSettings()
        settings.set_parameter("time_limit", 30)
        p.solve(settings)
        return p, v

    for label, make in (("cuopt-lp-default", lambda: lp(None)), ("cuopt-lp-pdlp", lambda: lp(SolverMethod.PDLP)),
                        ("cuopt-milp", milp)):
        runs = []
        for _ in range(2):
            start = time.perf_counter()
            p, variables = make()
            values = [float(v.getValue()) for v in variables]
            runs.append({"status": str(p.Status), "objective": float(p.ObjValue), "values": values,
                         "solver_seconds": float(p.SolveTime), "seconds": round(time.perf_counter() - start, 4),
                         "bits": bits([float(p.ObjValue), *values])})
        emit(probe=label, first=runs[0], second={k: runs[1][k] for k in ("status", "objective", "solver_seconds")},
             repeat_bit_identical=runs[0]["bits"] == runs[1]["bits"])


def device() -> None:
    smi = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,compute_cap,memory.total",
                          "--format=csv,noheader"], capture_output=True, text=True)
    with open("/opt/gpu/variant.json", encoding="utf-8") as handle:
        held = json.load(handle)
    emit(probe="device", nvidia_smi=smi.stdout.strip(), variant=held)


def main(argv: list[str]) -> int:
    if argv[:1] == ["cuopt"]:
        cuopt_probes()
        return 0
    size = int(argv[0]) if argv else 300
    device()
    highs_probes(size)
    with open("/opt/gpu/variant.json", encoding="utf-8") as handle:
        if not json.load(handle).get("cuopt_python"):
            emit(probe="cuopt", skipped="this image has no cuOpt (the highs-check build)")
            return 0
    done = subprocess.run([os.environ.get("CUOPT_PYTHON", "/opt/gpu/cuopt/bin/python"), os.path.abspath(__file__), "cuopt"],
                          capture_output=True, text=True, timeout=1800)
    sys.stdout.write(done.stdout)
    if done.returncode:
        emit(probe="cuopt", error=done.stderr[-1500:])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
