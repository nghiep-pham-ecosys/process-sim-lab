# Heat exchanger

A counter-current heat exchanger sized by the log mean temperature difference (LMTD).

Code: [`src/process_sim_lab/units/heat_exchanger.py`](../../src/process_sim_lab/units/heat_exchanger.py) ·
tests: [`tests/test_heat_exchanger.py`](../../tests/test_heat_exchanger.py)

## Model

Steady state, terminal temperatures known:

```text
terminal differences   dT1 = T_hot,in  - T_cold,out                    [K]
                       dT2 = T_hot,out - T_cold,in                     [K]
log mean difference    LMTD = (dT1 - dT2) / ln(dT1 / dT2)              [K]
equal-difference limit LMTD -> dT1 = dT2   as dT1 / dT2 -> 1
rate equation          Q = U * A * LMTD  =>  A = Q / (U * LMTD)        [m2]
```

Assumptions: pure counter-current flow (no F correction factor), constant overall coefficient U along the exchanger,
constant specific heats, no heat loss to the surroundings, no phase change inside the exchanger. A temperature cross
(a terminal difference ≤ 0) is rejected.

## Example

Terminal differences 80 K and 60 K give LMTD = 20 / ln(4/3) = 69.5212 K, and A = 5e5 / (500 × 69.5212) = 14.3841 m²:

```python
from process_sim_lab.units import counter_current_area, log_mean_temperature_difference

print(log_mean_temperature_difference(80.0, 60.0))     # 69.5211899...
r = counter_current_area(duty=5e5, overall_u=500.0,                 # W, W/(m2 K)
                         hot_in=423.15, hot_out=363.15, cold_in=303.15, cold_out=343.15)   # K
print(r.area)                                          # 14.3841036... m2
assert abs(log_mean_temperature_difference(80.0, 60.0) - 69.5211899356) < 1e-6
assert abs(r.area - 14.3841036) < 1e-6
```

## In a flowsheet and as a tool

- Flowsheet unit type `heat_exchanger`, one inlet and one outlet. Params: `temperature` (outlet, K),
  `heat_capacities` (J/(mol K) by component), `overall_u` (W/(m² K)), `utility_in` and `utility_out` (K). The duty is
  a sensible-heat balance, Q = Σ F_i·cp_i·|T_in − T_out|; the process stream is the hot side when it cools and the
  cold side when it heats. Sizing: `duty` (W), `area` (m²) and `lmtd` (K).
- Agent tool `heat_exchanger_area` (see [Agent layer and MCP](../agent.md)).

## Source

F. P. Incropera, D. P. DeWitt et al., *Fundamentals of Heat and Mass Transfer*, ch. 11 (log mean temperature
difference method for the counterflow exchanger); R. M. Felder and R. W. Rousseau, *Elementary Principles of Chemical
Processes*, ch. 8 (sensible heat with constant heat capacities, the duty in a flowsheet).
