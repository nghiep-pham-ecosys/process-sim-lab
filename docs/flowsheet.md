# Flowsheet

A sequential-modular flowsheet defined in JSON: feed streams and units joined by named streams, solved unit by unit,
with recycle loops converged by tearing a stream.

Code: [`src/process_sim_lab/flowsheet.py`](../src/process_sim_lab/flowsheet.py) (solver, JSON form, sizing) and
[`src/process_sim_lab/flowsheet_json.py`](../src/process_sim_lab/flowsheet_json.py) (result schema, command line) ·
tests: [`tests/test_flowsheet.py`](../tests/test_flowsheet.py) and
[`tests/test_flowsheet_json.py`](../tests/test_flowsheet_json.py)

## Model

Each stream is produced by at most one unit and consumed by at most one unit. A stream that no unit produces is a
feed; a stream that no unit consumes is a product. A recycle loop is broken by a tear stream: the solver guesses it,
runs every unit once in a calculation order (a topological sort with the tear streams cut), and compares the guess
with the value the pass computes.

```text
tear variables      x = (F_1, ..., F_n, T, P) of each tear stream            [mol/s, K, Pa]
one pass            g(x) = tear values computed by running the units in order with the guess x
fixed point         x* = g(x*)
scaled residual     r(x) = max_i |g_i(x) - x_i| / max(1, |x_i|)
converged when      r(x) <= tol

direct substitution x_(k+1) = g(x_k)
Wegstein            s_i = (g_i(x_k) - g_i(x_(k-1))) / (x_k,i - x_(k-1),i)
                    q_i = s_i / (s_i - 1),  bounded to [q_min, q_max]
                    x_(k+1),i = q_i * x_k,i + (1 - q_i) * g_i(x_k)
```

Unit types: `mixer`, `splitter`, `cstr`, `pfr`, `flash`, `heat_exchanger` and `shortcut_column`. Each unit page lists
its params and its sizing fields. Sizing runs once, on the converged streams.

## Example

The week-3 example, [`examples/reactor_flash_recycle.json`](../examples/reactor_flash_recycle.json), is a CSTR, a
flash drum and a purged vapour recycle. Wegstein converges it in 3 passes:

```python
from process_sim_lab.flowsheet import Flowsheet, solve_flowsheet

r = solve_flowsheet(Flowsheet.load("examples/reactor_flash_recycle.json"))
print(r.iterations, r.residual)          # 3 passes, residual below the stated tol of 1e-10
print(r.streams["recycle"].flows)        # about {'A': 1.0, 'I': 0.6, 'B': 0.4} mol/s
print(r.units["drum"].sizing["diameter"])   # about 0.206 m
assert r.iterations == 3 and r.residual <= 1e-10
assert all(abs(v) < 1e-9 for v in r.overall_balance().values())
```

The same from the command line, with the result checked against `RESULT_SCHEMA` (JSON Schema draft 2020-12):

```bash
python3 -m process_sim_lab.flowsheet_json solve examples/reactor_flash_recycle.json -o result.json
python3 -m process_sim_lab.flowsheet_json check result.json      # result.json: valid
```

The [worked example](flowsheet-worked-example.md) derives the answer by hand, runs direct substitution and Wegstein
side by side, sizes the drum and checks the JSON. The [local demo](demo.md) solves the same flowsheet from a form.

## Sources

R. M. Felder and R. W. Rousseau, *Elementary Principles of Chemical Processes*, ch. 4 (recycle and purge) and ch. 8
(sensible heat); A. W. Westerberg, H. P. Hutchison, R. L. Motard and P. Winter, *Process Flowsheeting*, Cambridge
University Press, 1979 (sequential-modular simulation, tear streams); J. H. Wegstein, "Accelerating convergence of
iterative processes", *Communications of the ACM* 1(6), 1958.
