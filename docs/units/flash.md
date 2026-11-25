# Flash drum and its sizing

An isothermal flash drum with given K-values, solved with the Rachford–Rice equation, and a vertical drum sized from
its vapour load by the Souders–Brown velocity.

Code: [`src/process_sim_lab/units/flash.py`](../../src/process_sim_lab/units/flash.py) and
[`src/process_sim_lab/units/flash_drum_sizing.py`](../../src/process_sim_lab/units/flash_drum_sizing.py) ·
tests: [`tests/test_flash.py`](../../tests/test_flash.py) and
[`tests/test_flash_drum_sizing.py`](../../tests/test_flash_drum_sizing.py)

## Flash model

Steady state, one equilibrium stage, vapour and liquid leave in equilibrium:

```text
feed mole fractions   z_i = F_i / F
equilibrium           y_i = K_i * x_i
vapour fraction       psi = V / F,  0 <= psi <= 1
component balance     x_i = z_i / (1 + psi * (K_i - 1)),   y_i = K_i * x_i
Rachford-Rice         f(psi) = sum_i z_i * (K_i - 1) / (1 + psi * (K_i - 1)) = 0
```

f(ψ) falls strictly on [0, 1], so the drum state follows from the two end values: f(0) ≤ 0 means the feed is at or
below its bubble point (all liquid, ψ = 0); f(1) ≥ 0 means it is at or above its dew point (all vapour, ψ = 1);
otherwise one root lies in (0, 1) and is found by bisection.

Assumptions: the K-values are given at the drum temperature and pressure and do not depend on composition (ideal
mixtures); the drum runs at the feed temperature and pressure; no reaction.

## Sizing model

The drum is a vertical cylinder sized so the vapour leaves slowly enough to drop its liquid:

```text
vapour molar mass        M_V = sum_i y_i * M_i                                   [kg/mol]
vapour density           rho_V = P * M_V / (R * T)        (ideal gas)            [kg/m3]
vapour volumetric flow   Q_V = V * R * T / P              (ideal gas)            [m3/s]
allowed vapour velocity  u_max = K_SB * sqrt((rho_L - rho_V) / rho_V)            [m/s]
cross-section            A = Q_V / u_max                                         [m2]
diameter                 D = sqrt(4 * A / pi)                                    [m]
height                   H = (H / D) * D                                         [m]
volume                   V_drum = pi * D^2 / 4 * H        (heads left out)       [m3]
```

K_SB is the Souders–Brown coefficient: about 0.07 m/s for a vertical drum with a demister pad. H / D is a design
choice, usually 3 to 5. Assumptions: ideal-gas vapour; the liquid density is given at drum conditions; the vapour load
sets the diameter (the liquid hold-up is not checked); the heads are not counted in the height or the volume.

## Examples

For z = (0.5, 0.5) and K = (2, 0.5) the Rachford–Rice root is ψ = 0.5, x = (1/3, 2/3), y = (2/3, 1/3):

```python
from process_sim_lab import Stream
from process_sim_lab.units import isothermal_flash

feed = Stream(flows={"A": 5.0, "B": 5.0}, temperature=350.0, pressure=1.5e5)
r = isothermal_flash(feed, k_values={"A": 2.0, "B": 0.5})
print(r.vapour_fraction, r.x["A"], r.y["A"])   # 0.5, 0.3333..., 0.6666...
assert abs(r.vapour_fraction - 0.5) < 1e-9
assert abs(r.x["A"] - 1 / 3) < 1e-9 and abs(r.y["A"] - 2 / 3) < 1e-9
```

The drum of the [worked example](../flowsheet-worked-example.md): vapour (1.25, 0.75, 0.5) mol/s at 330 K and 2 bar,
M = (60, 28, 60) g/mol, liquid 800 kg/m³, K_SB = 0.07 m/s, H / D = 4. The vapour density is
2e5 × 0.0504 / (8.314 × 330) = 3.674 kg/m³, and the drum comes out at D = 0.206 m and H = 0.823 m:

```python
from process_sim_lab import Stream
from process_sim_lab.units import size_vertical_flash_drum

vapour = Stream(flows={"A": 1.25, "I": 0.75, "B": 0.5}, temperature=330.0, pressure=2e5)
d = size_vertical_flash_drum(vapour, molar_masses={"A": 0.06, "I": 0.028, "B": 0.06},
                             liquid_density=800.0, souders_brown_k=0.07, height_to_diameter=4.0)
print(d.diameter, d.height, d.volume)   # 0.2058... m, 0.8234... m, 0.0274... m3
assert abs(d.vapour_molar_mass - 0.0504) < 1e-12
assert abs(d.diameter - 0.2058) < 1e-4 and abs(d.height - 0.8234) < 1e-4
```

## In a flowsheet and as a tool

- Flowsheet unit type `flash`, one inlet and two outlets (vapour, then liquid). Params: `k_values`, and optional
  `tol` and `max_iter` for the bisection. The four sizing params `molar_masses` (kg/mol), `liquid_density` (kg/m³),
  `souders_brown_k` (m/s) and `height_to_diameter` come all together or not at all. With them, the sizing holds
  `diameter`, `height`, `volume`, `height_to_diameter`, `vapour_density`, `vapour_volumetric_flow` and
  `max_vapour_velocity`; without them it is empty.
- Agent tool `flash_drum` (see [Agent layer and MCP](../agent.md)); the drum is sized through `solve_flowsheet`.

## Sources

H. H. Rachford Jr. and J. D. Rice, "Procedure for use of electronic digital computers in calculating flash
vaporization hydrocarbon equilibrium", *Journal of Petroleum Technology* 4(10), 1952; J. D. Seader, E. J. Henley and
D. K. Roper, *Separation Process Principles*, ch. 4 (single equilibrium stages and flash calculations).
M. Souders Jr. and G. G. Brown, "Design of fractionating columns. I. Entrainment and capacity", *Industrial and
Engineering Chemistry* 26(1), 1934; P. C. Wankat, *Separation Process Engineering*, ch. 2 (size of a vertical flash
drum); G. Towler and R. Sinnott, *Chemical Engineering Design*, ch. 16 (gas–liquid separators).
