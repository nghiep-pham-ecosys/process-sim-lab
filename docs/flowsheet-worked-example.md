# Worked example: a reactor, a flash drum and a purged recycle

This page solves the week-3 example flowsheet by hand, then with the library, sizes its equipment, and checks the JSON
output against its schema. Every number below comes from the hand derivation or from a run of the commands shown.

Files:

- spec: [`examples/reactor_flash_recycle.json`](../examples/reactor_flash_recycle.json)
- result: [`examples/reactor_flash_recycle.result.json`](../examples/reactor_flash_recycle.result.json)
- solver: [`src/process_sim_lab/flowsheet.py`](../src/process_sim_lab/flowsheet.py)
- result schema and command line: [`src/process_sim_lab/flowsheet_json.py`](../src/process_sim_lab/flowsheet_json.py)

## 1. The process

Three components: A (reactant), I (inert) and B (product). All flows are in mol/s, at 330 K and 2 bar.

```
feed ──► mixer ──reactor-in──► reactor ──reactor-out──► drum ──liquid──► product
           ▲                    (CSTR)                  (flash)
           │                                              │ vapour
           └────────recycle──────── purge-split ◄─────────┘
                                         │
                                         └──purge──► product
```

| Unit | Type | Data |
|---|---|---|
| `mixer` | mixer | feed A = 5.6, I = 2.4 |
| `reactor` | CSTR, A → B, first order | k = 0.023 1/s, V = 2 m3, Q = 0.02 m3/s, so τ = V / Q = 100 s and Da = kτ = 2.3 |
| `drum` | isothermal flash | K = (5, 1, 1/3) for (A, I, B); sizing data (illustrative): M = (60, 28, 60) g/mol, liquid 800 kg/m3, K_SB = 0.07 m/s, H / D = 4 |
| `purge-split` | splitter | 20 % of the vapour to purge, 80 % to recycle |

The recycle closes a loop: `mixer` needs `recycle`, which comes out of the last unit. The spec breaks the loop by
naming `recycle` as the tear stream:

```json
"tear": {"streams": ["recycle"], "method": "wegstein", "tol": 1e-10, "max_iter": 100}
```

## 2. The answer by hand

The example was built backwards from a chosen state, so the converged answer is exact.

1. Choose the reactor outlet C = (2, 3, 5), total 10. Then z = (0.2, 0.3, 0.5).
2. Flash (Rachford–Rice): Σ z_i (K_i − 1) / (1 + ψ (K_i − 1)) = 0 gives
   0.8 / (1 + 4ψ) = (1/3) / (1 − 2ψ/3), so ψ = 1/4. The vapour is y_i = z_i K_i / (1 + ψ (K_i − 1)) times V = 2.5:
   y = (0.5, 0.3, 0.2), vapour = (1.25, 0.75, 0.5). The liquid is the rest: (0.75, 2.25, 4.5).
3. Split: recycle = 0.8 × vapour = (1, 0.6, 0.4); purge = 0.2 × vapour = (0.25, 0.15, 0.1).
4. Reactor: X = Da / (1 + Da) = 2.3 / 3.3. The outlet A is 2, so the inlet A is 2 × (1 + Da) = 6.6, and
   the reaction makes 4.6 B. The reactor inlet is (6.6, 3, 0.4).
5. Mixer: feed = reactor inlet − recycle = (5.6, 2.4, 0). This is the feed in the spec, so the state is a fixed point.

Overall balance: feed A 5.6 − reacted 4.6 = 1.0 = liquid 0.75 + purge 0.25. Feed I 2.4 = 2.25 + 0.15. Made B 4.6 =
4.5 + 0.1. Each component closes.

`tests/test_flowsheet.py` repeats this derivation in exact fractions (`constructed_case`).

## 3. Solve it

```bash
python3 -m pip install -e .
python3 -m process_sim_lab.flowsheet_json solve examples/reactor_flash_recycle.json -o result.json
# result.json: 3 passes, residual 1.441e-12
```

Or from Python:

```python
from process_sim_lab.flowsheet import Flowsheet, solve_flowsheet

r = solve_flowsheet(Flowsheet.load("examples/reactor_flash_recycle.json"))
print(r.iterations, r.residual)     # 3 1.4407364190560656e-12
print(r.streams["recycle"].flows)   # {'A': 1.000000000000322, 'I': 0.6000000000004364, 'B': 0.4000000000002935}
print(r.overall_balance())          # every component within 1.5e-12 of 0
```

The solver finds the calculation order `mixer → reactor → drum → purge-split` by a topological sort with the tear
stream cut. One pass runs the four units once with the current guess of `recycle` and returns a new value g(x).

Converged streams (rounded to 12 decimals), against the hand answer:

| Stream | A | I | B | Hand answer |
|---|---|---|---|---|
| `reactor-in` | 6.6 | 3.0 | 0.4 | (6.6, 3, 0.4) |
| `reactor-out` | 2.0 | 3.0 | 5.000000000001 | (2, 3, 5) |
| `vapour` | 1.249999999999 | 0.749999999999 | 0.499999999999 | (1.25, 0.75, 0.5) |
| `liquid` | 0.750000000001 | 2.250000000002 | 4.500000000002 | (0.75, 2.25, 4.5) |
| `recycle` | 1.0 | 0.6 | 0.4 | (1, 0.6, 0.4) |
| `purge` | 0.25 | 0.15 | 0.1 | (0.25, 0.15, 0.1) |

## 4. Successive substitution against Wegstein

The scaled residual is r = max_i |g_i(x) − x_i| / max(1, |x_i|) over the tear variables (flows, T, P). Both runs
start from a zero recycle:

| Pass | Direct substitution | Wegstein |
|---|---|---|
| 1 | 8.970e-01 | 8.970e-01 |
| 2 | 9.242e-02 | 9.242e-02 |
| 3 | 9.522e-03 | **1.441e-12** |
| 4 | 9.810e-04 | |
| 5 | 1.011e-04 | |
| 6 | 1.041e-05 | |
| 7 | 1.073e-06 | |
| 8 | 1.105e-07 | |
| 9 | 1.139e-08 | |
| 10 | 1.173e-09 | |
| 11 | 1.213e-10 | |
| 12 | 1.292e-11 | |

Direct substitution (`"method": "direct"`) cuts the residual by a factor of about 0.103 per pass, so it takes 12
passes to reach 1e-10. Wegstein takes the same first step (a secant needs two points), then fits a secant to each tear
variable and jumps to where that line meets x = g(x). Here the jump lands within 1.4e-12 and the run stops at pass 3.

Both results depend on the zero first guess. g(0) = 0.897 × (1, 0.6, 0.4), which points the same way as the answer.
Every later iterate stays on that line, and along it g is affine with the same slope, 0.103, in every component. That
slope is the 0.103 per pass of direct substitution, and it makes each per-variable secant exact after two points.

Off that line the loop is slower. The slowest mode is the inert: I passes the reactor unchanged, and with K_I = 1 the
flash sends the fraction ψ = 1/4 of it to the vapour without changing ψ. A change in the recycle I therefore comes back
0.8 × 1/4 = 0.2 times as large. With a first guess of recycle = (0, 2, 0) mol/s:

| Method | Passes | Residual history |
|---|---|---|
| Direct substitution | 16 | 8.970e-01, 3.024e-01, 6.676e-02, … falling by 0.200 per pass … 6.127e-11 |
| Wegstein | 5 | 8.970e-01, 3.024e-01, 3.553e-02, 7.264e-04, 2.140e-12 |

Wegstein still wins, by 5 passes against 16, but it no longer lands in one jump.

To repeat the runs: `solve_flowsheet(Flowsheet.load(...), method="direct")`, and for the second table add
`"initial": {"recycle": {"flows": {"A": 0.0, "I": 2.0, "B": 0.0}, "temperature": 330.0, "pressure": 200000.0}}` to
`tear` in a copy of the spec.

## 5. Check the JSON output against the schema

`FlowsheetResult.to_dict()` writes the whole result as one JSON object. The same object is the `result` of the
`solve_flowsheet` tool in the agent layer. `RESULT_SCHEMA` describes it (JSON Schema draft 2020-12):

```bash
python3 -m process_sim_lab.flowsheet_json check examples/reactor_flash_recycle.result.json
# examples/reactor_flash_recycle.result.json: valid
python3 -m process_sim_lab.flowsheet_json schema     # prints RESULT_SCHEMA
```

The check has two layers:

1. The schema: required keys and no others, method and unit type from fixed lists, flows ≥ 0, temperature and
   pressure > 0, sizing fields from a fixed list and > 0, finite numbers only, at least one pass.
2. Checks a schema keyword cannot express: every stream a unit, feed list or product list names exists; every stream
   is a feed or a unit outlet; every component in a flow or a generation is listed; `history` has one entry per pass,
   ends with `residual`, and `residual` ≤ `tol`; each unit's `sizing` has exactly the fields of its type.

A change that breaks the output fails in place. For example, a misspelt inlet:

```
$.units.mixer.inlets[1]: names stream 'recycel', which is not in $.streams
```

`tests/test_flowsheet_json.py` checks that the committed result file is valid, matches a fresh solve within 1e-9 and
holds the hand answer within 1e-8 mol/s.

## 6. Size the equipment

After the loop converges, each unit is sized once from the converged streams. The result carries a `sizing` object
per unit, in SI units: the plain parametric data a CAD script can read later.

Reactor: the volume is a spec value, V = 2 m3, and the space time is τ = V / Q = 2 / 0.02 = 100 s.

Drum (vertical, Souders–Brown, `src/process_sim_lab/units/flash_drum_sizing.py`), from the vapour (1.25, 0.75, 0.5)
mol/s, 2.5 mol/s in all, at 330 K and 2 bar:

1. Vapour molar mass M_V = (1.25 × 0.060 + 0.75 × 0.028 + 0.5 × 0.060) / 2.5 = 0.0504 kg/mol.
2. Ideal gas, RT = 8.314462618 × 330 = 2743.77 J/mol: ρ_V = P M_V / RT = 2e5 × 0.0504 / 2743.77 = 3.674 kg/m3, and
   Q_V = 2.5 × 2743.77 / 2e5 = 0.03430 m3/s.
3. Allowed velocity u_max = K_SB √((ρ_L − ρ_V) / ρ_V) = 0.07 × √(796.33 / 3.674) = 1.0306 m/s.
4. Cross-section A = Q_V / u_max = 0.03328 m2, so D = √(4A / π) = 0.2058 m, H = 4D = 0.8234 m, and the cylinder
   volume π D² H / 4 = 0.02740 m3.

The drum is small because the example's flows are small (2.5 mol/s of vapour). In the result file:

```json
"sizing": {
  "diameter": 0.20584506300129932,
  "height": 0.8233802520051973,
  "volume": 0.02740130448602101,
  "height_to_diameter": 4.0,
  "vapour_density": 3.673773754032588,
  "vapour_volumetric_flow": 0.03429715829983586,
  "max_vapour_velocity": 1.0305933740631816
}
```

The mixer and the splitter have nothing to size: their `sizing` is `{}`. A flash without the four sizing params is
not sized either. A `heat_exchanger` unit reports its duty, area and LMTD, and a `shortcut_column` unit its minimum
stages, stages, minimum reflux and reflux ratio (the fields and models: the docstring of
[`src/process_sim_lab/flowsheet.py`](../src/process_sim_lab/flowsheet.py)).

## 7. Where the tear goes

`recycle` is the natural tear here. With a zero first guess the mixer still passes the fresh feed, so every unit gets
flow on the first pass. Tearing `reactor-in` or `reactor-out` instead also works, but the tear then needs an `initial`
guess in `tear`: with zero flow the flash drum gets an empty feed on the first pass, and the solver stops with an
error that names the unit and the unguessed tear stream.
