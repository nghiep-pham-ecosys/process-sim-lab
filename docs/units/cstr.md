# CSTR

An isothermal continuous stirred-tank reactor with one first-order, irreversible, liquid-phase reaction A → B.

Code: [`src/process_sim_lab/units/cstr.py`](../../src/process_sim_lab/units/cstr.py) ·
tests: [`tests/test_cstr.py`](../../tests/test_cstr.py)

## Model

Constant density, steady state, perfect mixing:

```text
space time        tau = V / Q                                     [s]
mole balance on A F_A0 - F_A - k * C_A * V = 0,  C_A = F_A / Q
                  =>  F_A = F_A0 / (1 + k * tau)
conversion        X = k * tau / (1 + k * tau)
Damkohler number  Da = k * tau
```

Assumptions: constant volumetric flow Q (liquid, no density change), isothermal, one reaction, B formed 1:1.

## Example

With k = 0.01 1/s, V = 2 m³ and Q = 0.004 m³/s, τ = 500 s and X = 5 / 6:

```python
from process_sim_lab import Stream
from process_sim_lab.units import isothermal_cstr_first_order

feed = Stream(flows={"A": 10.0, "W": 50.0}, temperature=330.0)        # mol/s, K
r = isothermal_cstr_first_order(feed, reactant="A", product="B",
                                rate_constant=0.01, volume=2.0, volumetric_flow=0.004)
print(r.space_time, r.conversion)   # 500.0 s, 0.8333...
assert abs(r.conversion - 5 / 6) < 1e-12
assert abs(r.outlet.flows["B"] - 10.0 * 5 / 6) < 1e-12
```

## In a flowsheet and as a tool

- Flowsheet unit type `cstr`, one inlet and one outlet. Params: `reactant`, `product`, `rate_constant` (1/s),
  `volume` (m³), `volumetric_flow` (m³/s). Sizing: `volume` (m³) and `space_time` (s).
- Agent tool `cstr` (see [Agent layer and MCP](../agent.md)).

## Source

H. S. Fogler, *Elements of Chemical Reaction Engineering*, ch. 5 (design equation of a CSTR, first-order reaction).
