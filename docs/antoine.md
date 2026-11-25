# Antoine vapour pressure

Pure-component vapour pressure from the Antoine equation, with constants from the NIST Chemistry WebBook.

Code: [`src/process_sim_lab/antoine.py`](../src/process_sim_lab/antoine.py) ·
tests: [`tests/test_antoine.py`](../tests/test_antoine.py)

## Model

The form used by the NIST Chemistry WebBook:

```text
log10(P / bar) = A - B / (T / K + C)

vapour pressure      P_sat(T) = 1e5 * 10 ** (A - B / (T + C))         [Pa]
saturation temp.     T_sat(P) = B / (A - log10(P / 1e5)) - C           [K]
```

A is dimensionless, B and C are in K. The constants are kept exactly as published (bar, K); the functions take and
return SI units (K, Pa) and convert only at that edge.

Assumptions: a pure liquid in equilibrium with its own vapour; the fit is used only inside the temperature range of
its data. Outside that range the functions raise `ValueError` instead of extrapolating.

| Component | A | B (K) | C (K) | Range (K) |
|---|---|---|---|---|
| benzene | 4.01814 | 1203.835 | −53.226 | 287.70 to 354.07 |
| toluene | 4.07827 | 1343.943 | −53.773 | 308.52 to 384.66 |
| ethylbenzene | 4.07488 | 1419.315 | −60.539 | 329.74 to 410.27 |

## Example

Benzene at 300 K: log10(P / bar) = 4.01814 − 1203.835 / (300 − 53.226), so P = 13 799 Pa. Its normal boiling point
is 353.3 K ± 0.1 K (NIST WebBook):

```python
from process_sim_lab.antoine import saturation_temperature, vapour_pressure

print(vapour_pressure("benzene", 300.0))               # 13799.09... Pa
print(saturation_temperature("benzene", 101_325.0))    # 353.25... K
assert abs(vapour_pressure("benzene", 300.0) - 13_799.0) < 1.0
assert abs(saturation_temperature("benzene", 101_325.0) - 353.3) < 0.1
```

As agent tools: `antoine_vapour_pressure` and `antoine_saturation_temperature` (see
[Agent layer and MCP](agent.md)).

## Source

NIST Chemistry WebBook, NIST Standard Reference Database 69, "Phase change data", table "Antoine Equation Parameters"
for each compound (accessed 2026-11-17). All three sets come from the row the WebBook attributes to Williamham,
Taylor, et al., 1945.
