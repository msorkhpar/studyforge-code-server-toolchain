"""cuOpt probes of the optimization-gpu variant: LPs and MILPs, each solve run twice, compared bit for bit.

    sh docs/measurements/optimization-gpu-probe.sh <gpu image> cuopt

Runs INSIDE the variant with `--gpus all --network none`. The image's python3 runs this file: it builds the
models (plain lists, a fixed-seed generator), solves the MILPs with HiGHS on the CPU for comparison, and runs
itself again under cuOpt's interpreter (/opt/gpu/cuopt/bin/python) for the cuOpt solves, passing the models as
JSON on stdin. One JSON object per line; cuOpt's own log lines are kept (`log`), trimmed.

* LP: the 2-variable LP (cuOpt's default method, which runs PDLP, barrier and dual simplex concurrently, and
  PDLP alone), and the 300x300 and 1000x1000 transportation LPs of optimization-gpu-probe.py.
* MILP: a 3-variable integer program, and a GridCap-like selection: 300 binary projects, 5 yearly budget rows
  with spend spread over 1 to 3 years, 30 mutually exclusive pairs; maximise value. Solved by cuOpt with its
  defaults, by cuOpt with `mip_determinism_mode` on, and by HiGHS (the CUDA build's CPU branch and bound).
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
import time

SEED = 20261112
MILP_SECONDS = 60


def emit(**record) -> None:
    print(json.dumps(record), flush=True)


def digest(values) -> str:
    return hashlib.sha256(struct.pack(f"<{len(values)}d", *values)).hexdigest()[:16]


class Lcg:
    def __init__(self, seed: int) -> None:
        self.state = seed

    def next(self, bound: int) -> int:
        self.state = (6364136223846793005 * self.state + 1442695040888963407) % 2**64
        return (self.state >> 33) % bound


# ------------------------------------------------------------------ the models, as CSR rows
def model(c, rows, lb, ub, integer, maximize):
    """rows: [(indices, values, row_lb, row_ub)] -> a dict both solvers read."""
    offsets, indices, values, rlb, rub = [0], [], [], [], []
    for idx, val, lo, hi in rows:
        indices += idx
        values += val
        offsets.append(len(indices))
        rlb.append(lo)
        rub.append(hi)
    return {"c": c, "offsets": offsets, "indices": indices, "values": values, "row_lb": rlb, "row_ub": rub,
            "lb": lb, "ub": ub, "integer": integer, "maximize": maximize}


INF = 1e30


def small_lp():
    return model([3.0, 2.0], [([0, 1], [1.0, 1.0], -INF, 4.0), ([0, 1], [1.0, 3.0], -INF, 6.0)],
                 [0.0, 0.0], [3.0, INF], [False, False], True)


def transport(n: int):
    rng = Lcg(SEED)
    costs = [float(1 + rng.next(99)) for _ in range(n * n)]
    supply = [n * 10 + (i % 7) for i in range(n)]
    total = sum(supply)
    demand = [total // n + (1 if j < total % n else 0) for j in range(n)]
    rows = [([i * n + j for j in range(n)], [1.0] * n, -INF, float(supply[i])) for i in range(n)]
    rows += [([i * n + j for i in range(n)], [1.0] * n, float(demand[j]), INF) for j in range(n)]
    return model(costs, rows, [0.0] * (n * n), [INF] * (n * n), [False] * (n * n), False)


def small_milp():
    rows = [([0, 1, 2], [2.0, 3.0, 1.0], -INF, 5.0), ([0, 1, 2], [4.0, 1.0, 2.0], -INF, 11.0),
            ([0, 1, 2], [3.0, 4.0, 2.0], -INF, 8.0)]
    return model([5.0, 4.0, 3.0], rows, [0.0] * 3, [10.0] * 3, [True] * 3, True)


def gridcap_like(projects: int = 300, years: int = 5):
    rng = Lcg(SEED + 1)
    spend = [[0.0] * projects for _ in range(years)]
    value = []
    for p in range(projects):
        start, length = rng.next(years), 1 + rng.next(3)
        total = 0.0
        for y in range(start, min(years, start + length)):
            amount = float(50 + rng.next(450))
            spend[y][p] = amount
            total += amount
        value.append(round(total * (0.8 + rng.next(60) / 100.0) + rng.next(40), 1))
    rows = []
    for y in range(years):
        idx = [p for p in range(projects) if spend[y][p]]
        rows.append((idx, [spend[y][p] for p in idx], -INF, round(0.35 * sum(spend[y]), 1)))
    for k in range(30):
        a, b = rng.next(projects), rng.next(projects)
        if a != b:
            rows.append(([min(a, b), max(a, b)], [1.0, 1.0], -INF, 1.0))
    return model(value, rows, [0.0] * projects, [1.0] * projects, [True] * projects, True)


# ------------------------------------------------------------------ HiGHS on the CPU (the image's python3)
def highs(m: dict) -> dict:
    import highspy

    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("time_limit", float(MILP_SECONDS))
    h.setOptionValue("threads", 1)
    n = len(m["c"])
    lp = highspy.HighsLp()
    lp.num_col_, lp.num_row_ = n, len(m["row_lb"])
    lp.col_cost_, lp.col_lower_ = m["c"], m["lb"]
    lp.col_upper_ = [min(u, highspy.kHighsInf) for u in m["ub"]]
    lp.row_lower_ = [max(v, -highspy.kHighsInf) for v in m["row_lb"]]
    lp.row_upper_ = [min(v, highspy.kHighsInf) for v in m["row_ub"]]
    lp.a_matrix_.format_ = highspy.MatrixFormat.kRowwise
    lp.a_matrix_.start_, lp.a_matrix_.index_, lp.a_matrix_.value_ = m["offsets"], m["indices"], m["values"]
    lp.integrality_ = [highspy.HighsVarType.kInteger if i else highspy.HighsVarType.kContinuous for i in m["integer"]]
    lp.sense_ = highspy.ObjSense.kMaximize if m["maximize"] else highspy.ObjSense.kMinimize
    h.passModel(lp)
    start = time.perf_counter()
    h.run()
    info = h.getInfo()
    return {"status": h.modelStatusToString(h.getModelStatus()), "objective": info.objective_function_value,
            "bound": info.mip_dual_bound, "gap": info.mip_gap, "nodes": info.mip_node_count,
            "seconds": round(time.perf_counter() - start, 3), "x": digest(list(h.getSolution().col_value))}


# ------------------------------------------------------------------ cuOpt (its venv)
def cuopt(m: dict, settings_in: dict) -> dict:
    import numpy as np
    from cuopt.linear_programming import DataModel, Solve, SolverSettings

    def arr(values):
        a = np.array(values, dtype=np.float64)
        return np.where(np.abs(a) >= INF, np.sign(a) * np.inf, a)

    d = DataModel()
    d.set_csr_constraint_matrix(np.array(m["values"], dtype=np.float64), np.array(m["indices"], dtype=np.int32),
                                np.array(m["offsets"], dtype=np.int32))
    d.set_constraint_lower_bounds(arr(m["row_lb"]))
    d.set_constraint_upper_bounds(arr(m["row_ub"]))
    d.set_objective_coefficients(np.array(m["c"], dtype=np.float64))
    d.set_variable_lower_bounds(np.array(m["lb"], dtype=np.float64))
    d.set_variable_upper_bounds(arr(m["ub"]))
    d.set_variable_types(np.array(["I" if i else "C" for i in m["integer"]]))
    d.set_maximize(m["maximize"])
    s = SolverSettings()
    for key, value in settings_in.items():
        s.set_parameter(key, value)
    log = f"/tmp/cuopt-{os.getpid()}.log"
    s.set_parameter("log_file", log)
    s.set_parameter("log_to_console", False)
    start = time.perf_counter()
    sol = Solve(d, s)
    seconds = time.perf_counter() - start
    x = [float(v) for v in sol.get_primal_solution()]
    out = {"status": str(sol.get_termination_status()), "reason": str(sol.get_termination_reason()),
           "objective": float(sol.get_primal_objective()), "seconds": round(seconds, 3),
           "solver_seconds": round(float(sol.get_solve_time()), 3), "x": digest(x)}
    if any(m["integer"]):
        stats = sol.get_milp_stats()
        out.update(gap=float(stats["mip_gap"]), bound=float(stats["solution_bound"]), nodes=int(stats["num_nodes"]))
    else:
        out.update(solved_by=str(sol.get_solved_by()), iterations=int(sol.get_lp_stats()["nb_iterations"]))
    try:
        with open(log, encoding="utf-8", errors="replace") as handle:
            # ⛔ cuOpt logs the card's UUID, which identifies one machine; that line is never kept.
            lines = [line.rstrip() for line in handle if line.strip() and "UUID" not in line]
        os.unlink(log)
    except OSError:
        lines = []
    out["log"] = lines
    return out


CASES = [
    ("lp-small-default", small_lp, {}),
    ("lp-small-pdlp", small_lp, {"method": 1}),
    ("lp-transport-300-default", lambda: transport(300), {}),
    ("lp-transport-300-pdlp", lambda: transport(300), {"method": 1}),
    ("lp-transport-1000-default", lambda: transport(1000), {}),
    ("lp-transport-1000-pdlp", lambda: transport(1000), {"method": 1}),
    ("milp-small", small_milp, {"time_limit": MILP_SECONDS}),
    ("milp-gridcap-like", gridcap_like, {"time_limit": MILP_SECONDS}),
    ("milp-gridcap-like-determinism", gridcap_like, {"time_limit": MILP_SECONDS, "mip_determinism_mode": 1}),
]


def child() -> int:
    """Under cuOpt's interpreter: solve each case twice, report both and whether the bits agree."""
    for name, build, settings in CASES:
        m = build()
        runs = []
        for _ in range(2):
            try:
                runs.append(cuopt(m, settings))
            except Exception as error:  # a refused setting is a result, not a crash
                runs.append({"error": f"{type(error).__name__}: {error}"[:300]})
        first, second = runs
        log = first.pop("log", [])
        second.pop("log", None)
        same = "x" in first and first.get("x") == second.get("x") and first.get("objective") == second.get("objective")
        keep = [l for l in log if "CPUFJ). Objective" not in l and any(
            k in l.lower() for k in ("gpu", "cuda", "device", "pdlp", "barrier", "simplex", "heuristic", "branch",
                                     "presolve", "solved", "optimal", "feasible", "gap", "explored", "version",
                                     "determinis", "worker", "thread"))]
        emit(probe=f"cuopt-{name}", settings=settings, first=first, second=second, repeat_bit_identical=same,
             log=keep[:40])
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["child"]:
        return child()
    for name, build in (("milp-small", small_milp), ("milp-gridcap-like", gridcap_like)):
        m = build()
        first, second = highs(m), highs(m)
        emit(probe=f"highs-cpu-{name}", variables=len(m["c"]), rows=len(m["row_lb"]), first=first,
             second={k: second[k] for k in ("status", "objective", "seconds")},
             repeat_bit_identical=first["x"] == second["x"] and first["objective"] == second["objective"])
    done = subprocess.run([os.environ.get("CUOPT_PYTHON", "/opt/gpu/cuopt/bin/python"), os.path.abspath(__file__), "child"],
                          capture_output=True, text=True, timeout=3600)
    sys.stdout.write(done.stdout)
    if done.returncode:
        emit(probe="cuopt", error=done.stderr[-2000:])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
