#!/bin/sh
# Proves the optimization profile's runner offline: every solver the course teaches loads and
# solves a tiny model, and OR-Tools and highspy load in one process in both import orders.
# Usage: IMAGE=<runner-optimization tag> sh docs/measurements/optimization-offline-proof.sh
# With no GRB_LICENSE_FILE it also proves the image holds no Gurobi license: the profile removes the
# license file the gurobipy wheel bundles, and a learner mounts their own read-only, for example
#   -v /path/to/gurobi.lic:/licenses/gurobi.lic:ro -e GRB_LICENSE_FILE=/licenses/gurobi.lic
set -eu
: "${IMAGE:?set IMAGE to the optimization runner tag}"
for order in "import highspy; import ortools.math_opt.python.mathopt" "import ortools.math_opt.python.mathopt; import highspy"; do
  docker run --rm --network none "$IMAGE" python3 -c "$order; print('import order ok:', '''$order''')"
done
docker run --rm -i --network none "$IMAGE" python3 - <<'PY'
from ortools.math_opt.python import mathopt
from ortools.sat.python import cp_model
import ortools
print("ortools", ortools.__version__)
for st in (mathopt.SolverType.HIGHS, mathopt.SolverType.GSCIP, mathopt.SolverType.CP_SAT,
           mathopt.SolverType.GLOP, mathopt.SolverType.PDLP):
    lp = st in (mathopt.SolverType.GLOP, mathopt.SolverType.PDLP)
    m = mathopt.Model()
    x = m.add_variable(lb=0, ub=10, is_integer=not lp, name="x")
    y = m.add_variable(lb=0, ub=10, name="y")
    m.add_linear_constraint(x + 2 * y <= 7)
    m.maximize(3 * x + y)
    r = mathopt.solve(m, st)
    assert r.termination.reason == mathopt.TerminationReason.OPTIMAL, st
    print(st.name, r.termination.reason.name, round(r.objective_value(), 4))
m = cp_model.CpModel(); a = m.new_int_var(0, 5, "a"); m.maximize(a)
s = cp_model.CpSolver(); assert s.solve(m) == cp_model.OPTIMAL; print("CP-SAT model", s.value(a))
import gurobipy as gp
import os
if os.environ.get("GRB_LICENSE_FILE"):
    g = gp.Model(); g.Params.OutputFlag = 0; z = g.addVar(ub=3); g.setObjective(z, gp.GRB.MAXIMIZE); g.optimize()
    print("gurobipy", gp.gurobi.version(), "with the mounted license:", g.ObjVal)
else:
    try:
        gp.Model()
        raise SystemExit("a Gurobi license was found in the image; none may be baked in")
    except gp.GurobiError as e:
        print("gurobipy", gp.gurobi.version(), "has no license in the image (error", e.errno, ")")
import pulp
p = pulp.LpProblem("t", pulp.LpMaximize); v = pulp.LpVariable("v", 0, 4, cat="Integer"); p += v
p.solve(pulp.PULP_CBC_CMD(msg=0)); assert pulp.LpStatus[p.status] == "Optimal"
print("pulp", pulp.__version__, "CBC", v.value())
import pyomo.environ as pe
mm = pe.ConcreteModel(); mm.x = pe.Var(bounds=(0, 2), domain=pe.Integers)
mm.o = pe.Objective(expr=mm.x, sense=pe.maximize)
print("pyomo highs", pe.SolverFactory("highs").solve(mm).solver.termination_condition, pe.value(mm.x))
import highspy, numpy, scipy, pandas, numpy_financial, matplotlib, hypothesis, fastapi, boto3, moto
print("highspy", highspy.Highs().version(), "pandas", pandas.__version__, "scipy", scipy.__version__)
PY
