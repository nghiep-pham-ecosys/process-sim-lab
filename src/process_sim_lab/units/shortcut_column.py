"""Shortcut distillation column: Fenske minimum stages, Underwood minimum reflux, Gilliland actual stages.

Model (steady state, constant relative volatilities, constant molar overflow, total condenser, partial reboiler):

    relative volatility   alpha_i, any common reference component; only ratios matter
    key specs             r_LK = fraction of the light key to the distillate, r_HK = fraction of the heavy key to
                          the bottoms; d_i and b_i are the distillate and bottoms flows of component i, mol/s

    Fenske (total reflux) N_min = ln[(r_LK / (1 - r_LK)) * (r_HK / (1 - r_HK))] / ln(alpha_LK / alpha_HK)
    non-key distribution  d_i / b_i = (alpha_i / alpha_HK)^N_min * (d_HK / b_HK)

    Underwood             sum_i alpha_i z_i / (alpha_i - theta) = 1 - q,    alpha_HK < theta < alpha_LK
                          R_min + 1 = sum_i alpha_i x_D,i / (alpha_i - theta)

    Gilliland (Molokanov) X = (R - R_min) / (R + 1)
                          Y = 1 - exp[(1 + 54.4 X) / (11 + 117.2 X) * (X - 1) / sqrt(X)]
                          N = (N_min + Y) / (1 - Y)

q is the feed condition: the fraction of the feed that joins the liquid below the feed stage (1 saturated liquid,
0 saturated vapour, > 1 subcooled liquid, < 0 superheated vapour). N_min and N count equilibrium stages with the
partial reboiler as one stage. N is not rounded up.

With adjacent keys (no component has a volatility between alpha_HK and alpha_LK), the Underwood sum rises strictly
on (alpha_HK, alpha_LK) from -inf to +inf, so it has exactly one root there for every q; it is found by bisection.
Keys with a component between them need one root per such component and are rejected here.

Assumptions: constant relative volatilities and constant molar overflow; the distillate composition in the Underwood
sum is the Fenske (total-reflux) distribution, the usual shortcut approximation; non-keys follow Fenske. The method
gives no temperatures or pressures: the distillate and bottoms streams carry the feed temperature and pressure only
because a Stream needs them.

Sources: M. R. Fenske, "Fractionation of straight-run Pennsylvania gasoline", Industrial and Engineering Chemistry
24(5), 1932; A. J. V. Underwood, "Fractional distillation of multicomponent mixtures", Chemical Engineering Progress
44, 1948; E. R. Gilliland, "Multicomponent rectification: estimation of the number of theoretical plates as a function
of the reflux ratio", Industrial and Engineering Chemistry 32(9), 1940; Y. K. Molokanov, T. P. Korablina,
N. I. Mazurina and G. A. Nikiforov, "An approximation method for calculating the basic parameters of multicomponent
fractionation", International Chemical Engineering 12(2), 1972 (the equation for Gilliland's curve); J. D. Seader,
E. J. Henley and D. K. Roper, Separation Process Principles, ch. 9 (the FUG method); P. C. Wankat, Separation Process
Engineering, 5th ed., ch. 7, Examples 7-1 and 7-2 (the test case).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from process_sim_lab.streams import Stream


@dataclass(frozen=True)
class ShortcutColumnResult:
    """Product streams and design numbers of a shortcut (FUG) column.

    Attributes:
        distillate: distillate, mol/s by component (feed temperature and pressure; not computed by the method).
        bottoms: bottoms, mol/s by component (feed temperature and pressure; not computed by the method).
        distillate_fraction: d_i / f_i of each component, the fraction of its feed that leaves in the distillate.
        minimum_stages: N_min from Fenske, equilibrium stages including the partial reboiler.
        theta: the Underwood root between alpha_HK and alpha_LK (same reference as the given volatilities).
        minimum_reflux: R_min = (L / D)_min from Underwood.
        reflux_ratio: the operating R = L / D.
        gilliland_x: X = (R - R_min) / (R + 1).
        gilliland_y: Y = (N - N_min) / (N + 1) from the Molokanov equation.
        stages: N from Gilliland, equilibrium stages including the partial reboiler, not rounded.
    """

    distillate: Stream
    bottoms: Stream
    distillate_fraction: dict[str, float]
    minimum_stages: float
    theta: float
    minimum_reflux: float
    reflux_ratio: float
    gilliland_x: float
    gilliland_y: float
    stages: float


def fenske_minimum_stages(
    light_key_recovery: float, heavy_key_recovery: float, relative_volatility: float
) -> float:
    """N_min = ln[(r_LK / (1 - r_LK)) (r_HK / (1 - r_HK))] / ln(alpha_LK / alpha_HK).

    Args:
        light_key_recovery: r_LK, fraction of the light key to the distillate, in (0, 1).
        heavy_key_recovery: r_HK, fraction of the heavy key to the bottoms, in (0, 1).
        relative_volatility: alpha_LK / alpha_HK, > 1.
    """
    for name, r in (("light_key_recovery", light_key_recovery), ("heavy_key_recovery", heavy_key_recovery)):
        if not 0.0 < r < 1.0:
            raise ValueError(f"{name} must be in (0, 1), got {r}")
    if not (math.isfinite(relative_volatility) and relative_volatility > 1.0):
        raise ValueError(f"alpha_LK / alpha_HK must be finite and > 1, got {relative_volatility}")
    if light_key_recovery + heavy_key_recovery <= 1.0:
        raise ValueError(
            f"light_key_recovery + heavy_key_recovery must be > 1 for a separation, got "
            f"{light_key_recovery} + {heavy_key_recovery}"
        )
    separation = (light_key_recovery / (1.0 - light_key_recovery)) * (heavy_key_recovery / (1.0 - heavy_key_recovery))
    return math.log(separation) / math.log(relative_volatility)


def molokanov_y(x: float) -> float:
    """Gilliland's Y = (N - N_min) / (N + 1) from X = (R - R_min) / (R + 1), Molokanov equation; X in [0, 1]."""
    if not 0.0 <= x <= 1.0:
        raise ValueError(f"Gilliland X must be in [0, 1], got {x}")
    if x == 0.0:
        return 1.0
    return 1.0 - math.exp((1.0 + 54.4 * x) / (11.0 + 117.2 * x) * (x - 1.0) / math.sqrt(x))


def _distillate_fraction(log_ratio: float) -> float:
    """d / f from ln(d / b), without overflow for a very large or very small ratio."""
    if log_ratio >= 0.0:
        return 1.0 / (1.0 + math.exp(-log_ratio))
    e = math.exp(log_ratio)
    return e / (1.0 + e)


def shortcut_column(
    feed: Stream,
    *,
    relative_volatilities: dict[str, float],
    light_key: str,
    heavy_key: str,
    light_key_recovery: float,
    heavy_key_recovery: float,
    q: float = 1.0,
    reflux_ratio: float | None = None,
    reflux_factor: float | None = None,
) -> ShortcutColumnResult:
    """Design a distillation column by the Fenske-Underwood-Gilliland shortcut method.

    Args:
        feed: inlet stream, total flow > 0; must contain both keys.
        relative_volatilities: alpha_i, > 0 and finite, against any one reference component, for every component
            with a positive flow. Entries for other components are ignored.
        light_key, heavy_key: names of the key components; alpha_LK > alpha_HK, and no component lies between them.
        light_key_recovery: fraction of the light key to the distillate, in (0, 1).
        heavy_key_recovery: fraction of the heavy key to the bottoms, in (0, 1); the two sum to more than 1.
        q: feed condition, the liquid fraction added below the feed stage (1 saturated liquid, 0 saturated vapour).
        reflux_ratio: operating R = L / D, > R_min. Give this or reflux_factor, not both.
        reflux_factor: R / R_min, > 1.

    Returns:
        ShortcutColumnResult with the product split, N_min, theta, R_min, R, the Gilliland X and Y, and N.
    """
    if (reflux_ratio is None) == (reflux_factor is None):
        raise ValueError("give exactly one of reflux_ratio and reflux_factor")
    if not math.isfinite(q):
        raise ValueError(f"q must be finite, got {q}")
    if light_key == heavy_key:
        raise ValueError("light_key and heavy_key must differ")
    total = feed.total_flow
    if total <= 0:
        raise ValueError("feed has no flow")

    present = {c: f for c, f in feed.flows.items() if f > 0}
    for key, role in ((light_key, "light key"), (heavy_key, "heavy key")):
        if key not in present:
            raise ValueError(f"{role} {key!r} has no flow in the feed")
    for c in present:
        if c not in relative_volatilities:
            raise ValueError(f"no relative volatility for component {c!r}")
        a = relative_volatilities[c]
        if not (math.isfinite(a) and a > 0):
            raise ValueError(f"relative volatility of {c!r} must be finite and > 0, got {a}")
    alpha = {c: relative_volatilities[c] for c in present}
    a_lk, a_hk = alpha[light_key], alpha[heavy_key]
    if not a_lk > a_hk:
        raise ValueError(f"light key {light_key!r} must be more volatile than heavy key {heavy_key!r}")
    between = sorted(c for c, a in alpha.items() if a_hk < a < a_lk)
    if between:
        raise ValueError(f"components {between} lie between the keys; only adjacent keys are supported")

    # Fenske: minimum stages and the split of every component at total reflux.
    n_min = fenske_minimum_stages(light_key_recovery, heavy_key_recovery, a_lk / a_hk)
    log_hk = math.log((1.0 - heavy_key_recovery) / heavy_key_recovery)  # ln(d_HK / b_HK)
    fraction = {c: _distillate_fraction(n_min * math.log(a / a_hk) + log_hk) for c, a in alpha.items()}
    fraction[light_key], fraction[heavy_key] = light_key_recovery, 1.0 - heavy_key_recovery
    d = {c: present[c] * fraction[c] for c in present}
    distillate_total = sum(d.values())

    # Underwood: the root theta between the keys, then the minimum reflux.
    z = {c: f / total for c, f in present.items()}

    def underwood(theta: float) -> float:
        return sum(alpha[c] * z[c] / (alpha[c] - theta) for c in z) - (1.0 - q)

    lo, hi = a_hk, a_lk  # underwood rises from -inf just above a_hk to +inf just below a_lk
    while True:
        mid = 0.5 * (lo + hi)
        if mid <= lo or mid >= hi:  # bracket at float resolution
            break
        if underwood(mid) < 0.0:
            lo = mid
        else:
            hi = mid
    theta = 0.5 * (lo + hi)
    r_min = sum(alpha[c] * d[c] / (alpha[c] - theta) for c in d) / distillate_total - 1.0
    if not r_min > 0.0:
        raise ValueError(f"Underwood gives R_min = {r_min:.6g} <= 0; the specs need no reflux by this method")

    # Gilliland: actual stages at the operating reflux.
    if reflux_ratio is None:
        if not (math.isfinite(reflux_factor) and reflux_factor > 1.0):
            raise ValueError(f"reflux_factor must be finite and > 1, got {reflux_factor}")
        r = reflux_factor * r_min
    else:
        if not (math.isfinite(reflux_ratio) and reflux_ratio > r_min):
            raise ValueError(f"reflux_ratio must be finite and > R_min = {r_min:.6g}, got {reflux_ratio}")
        r = reflux_ratio
    x = (r - r_min) / (r + 1.0)
    y = molokanov_y(x)
    if not y < 1.0:  # X below about 1e-5 rounds Y to 1: infinitely many stages
        raise ValueError(f"reflux R = {r:.10g} is too close to R_min = {r_min:.10g} for a finite stage count")
    n = (n_min + y) / (1.0 - y)

    state = dict(temperature=feed.temperature, pressure=feed.pressure)
    distillate = {c: d.get(c, 0.0) for c in feed.flows}
    bottoms = {c: max(0.0, feed.flows[c] - distillate[c]) for c in feed.flows}
    return ShortcutColumnResult(
        distillate=Stream(flows=distillate, **state),
        bottoms=Stream(flows=bottoms, **state),
        distillate_fraction={c: fraction.get(c, 0.0) for c in feed.flows},
        minimum_stages=n_min,
        theta=theta,
        minimum_reflux=r_min,
        reflux_ratio=r,
        gilliland_x=x,
        gilliland_y=y,
        stages=n,
    )
