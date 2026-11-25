# Shortcut column

A distillation column designed by the Fenske–Underwood–Gilliland (FUG) shortcut method: Fenske minimum stages,
Underwood minimum reflux, Gilliland actual stages.

Code: [`src/process_sim_lab/units/shortcut_column.py`](../../src/process_sim_lab/units/shortcut_column.py) ·
tests: [`tests/test_shortcut_column.py`](../../tests/test_shortcut_column.py)

## Model

Steady state, constant relative volatilities, constant molar overflow, total condenser, partial reboiler:

```text
key specs             r_LK = fraction of the light key to the distillate
                      r_HK = fraction of the heavy key to the bottoms

Fenske (total reflux) N_min = ln[(r_LK / (1 - r_LK)) * (r_HK / (1 - r_HK))] / ln(alpha_LK / alpha_HK)
non-key distribution  d_i / b_i = (alpha_i / alpha_HK)^N_min * (d_HK / b_HK)

Underwood             sum_i alpha_i z_i / (alpha_i - theta) = 1 - q,    alpha_HK < theta < alpha_LK
                      R_min + 1 = sum_i alpha_i x_D,i / (alpha_i - theta)

Gilliland (Molokanov) X = (R - R_min) / (R + 1)
                      Y = 1 - exp[(1 + 54.4 X) / (11 + 117.2 X) * (X - 1) / sqrt(X)]
                      N = (N_min + Y) / (1 - Y)
```

q is the feed condition (1 saturated liquid, 0 saturated vapour). N_min and N count equilibrium stages with the
partial reboiler as one stage; N is not rounded up. The keys must be adjacent: no component has a volatility between
them, so the Underwood equation has exactly one root between α_HK and α_LK, found by bisection.

Assumptions: constant relative volatilities and constant molar overflow; the distillate composition in the Underwood
sum is the Fenske (total-reflux) distribution; non-keys follow Fenske. The method gives no temperatures or pressures.

## Example

Wankat, Examples 7-1 and 7-2: a saturated vapour feed (q = 0) of 40 % benzene, 30 % toluene and 30 % cumene,
α = (2.25, 1.0, 0.21) against toluene, 95 % of toluene to the distillate and 98 % of cumene to the bottoms.
N_min = ln(931) / ln(1 / 0.21) = 4.3804 and the book prints (L / D)_min = 0.6663:

```python
import math
from process_sim_lab import Stream
from process_sim_lab.units import shortcut_column

feed = Stream(flows={"benzene": 40.0, "toluene": 30.0, "cumene": 30.0})     # mol/s
r = shortcut_column(feed, relative_volatilities={"benzene": 2.25, "toluene": 1.0, "cumene": 0.21},
                    light_key="toluene", heavy_key="cumene",
                    light_key_recovery=0.95, heavy_key_recovery=0.98, q=0.0, reflux_factor=1.2)
print(r.minimum_stages, r.minimum_reflux, r.reflux_ratio, r.stages)   # 4.380, 0.666, 0.799, 11.8
assert abs(r.minimum_stages - math.log(931.0) / math.log(1.0 / 0.21)) < 1e-12
assert abs(r.minimum_reflux - 0.6663) < 0.001 * 0.6663
```

## In a flowsheet and as a tool

- Flowsheet unit type `shortcut_column`, one inlet and two outlets (distillate, then bottoms). Params:
  `relative_volatilities`, `light_key`, `heavy_key`, `light_key_recovery`, `heavy_key_recovery`, optional `q`, and
  `reflux_ratio` or `reflux_factor` (not both). Sizing: `minimum_stages`, `stages`, `minimum_reflux` and
  `reflux_ratio`.
- Agent tool `shortcut_column` (see [Agent layer and MCP](../agent.md)).

## Sources

M. R. Fenske, "Fractionation of straight-run Pennsylvania gasoline", *Industrial and Engineering Chemistry* 24(5),
1932; A. J. V. Underwood, "Fractional distillation of multicomponent mixtures", *Chemical Engineering Progress* 44,
1948; E. R. Gilliland, "Multicomponent rectification: estimation of the number of theoretical plates as a function of
the reflux ratio", *Industrial and Engineering Chemistry* 32(9), 1940; Y. K. Molokanov et al., "An approximation
method for calculating the basic parameters of multicomponent fractionation", *International Chemical Engineering*
12(2), 1972; J. D. Seader, E. J. Henley and D. K. Roper, *Separation Process Principles*, ch. 9; P. C. Wankat,
*Separation Process Engineering*, 5th ed., ch. 7, Examples 7-1 and 7-2 (the test case).
