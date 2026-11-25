# PFR

An isothermal plug-flow reactor with one first-order, irreversible, liquid-phase reaction A → B.

Code: [`src/process_sim_lab/units/pfr.py`](../../src/process_sim_lab/units/pfr.py) ·
tests: [`tests/test_pfr.py`](../../tests/test_pfr.py)

## Model

Constant density, steady state, plug flow (no axial mixing, no radial gradients):

```text
space time        tau = V / Q                                     [s]
mole balance on A dF_A/dV = -k * C_A,  C_A = F_A / Q
                  =>  F_A = F_A0 * exp(-k * tau)
conversion        X = 1 - exp(-k * tau)
```

Assumptions: constant volumetric flow Q (liquid, no density change), isothermal, one reaction, B formed 1:1.

The tests check the closed form against a hand-derived case (k·τ = ln 2 gives X = 1/2) and against the limit of N
equal CSTRs in series, X_N = 1 − (1 + k·τ / N)^−N, which tends to 1 − exp(−k·τ).

## Example

```python
import math
from process_sim_lab import Stream
from process_sim_lab.units import isothermal_pfr_first_order

feed = Stream(flows={"A": 10.0, "W": 50.0}, temperature=330.0)        # mol/s, K
r = isothermal_pfr_first_order(feed, reactant="A", product="B",
                               rate_constant=math.log(2) / 100, volume=1.0, volumetric_flow=0.01)
print(r.space_time, r.conversion)   # 100.0 s, 0.5
assert abs(r.conversion - 0.5) < 1e-12
```

## In a flowsheet and as a tool

- Flowsheet unit type `pfr`, one inlet and one outlet. Params: `reactant`, `product`, `rate_constant` (1/s),
  `volume` (m³), `volumetric_flow` (m³/s). Sizing: `volume` (m³) and `space_time` (s).
- Agent tool `pfr` (see [Agent layer and MCP](../agent.md)).

## Source

H. S. Fogler, *Elements of Chemical Reaction Engineering*, ch. 5 (design equation of a tubular reactor, first-order
reaction); O. Levenspiel, *Chemical Reaction Engineering*, ch. 5 (steady-state plug flow reactor).
