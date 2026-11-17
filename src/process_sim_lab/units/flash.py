"""Isothermal flash drum with given K-values, solved with the Rachford-Rice equation.

Model (steady state, one equilibrium stage, vapour and liquid leave in equilibrium):

    feed mole fractions   z_i = F_i / F
    equilibrium           y_i = K_i * x_i
    vapour fraction       psi = V / F,  0 <= psi <= 1
    component balance     x_i = z_i / (1 + psi * (K_i - 1)),   y_i = K_i * x_i
    Rachford-Rice         f(psi) = sum_i z_i * (K_i - 1) / (1 + psi * (K_i - 1)) = 0

f(psi) falls strictly on [0, 1] (f' = -sum_i z_i (K_i - 1)^2 / (1 + psi (K_i - 1))^2 < 0), and with K_i > 0 its poles
psi = 1 / (1 - K_i) all lie outside [0, 1]. So the drum state follows from the two end values:

    f(0) = sum_i z_i K_i - 1 <= 0      feed at or below its bubble point: all liquid, psi = 0
    f(1) = 1 - sum_i z_i / K_i >= 0    feed at or above its dew point: all vapour, psi = 1
    otherwise                          one root in (0, 1), found here by bisection

Assumptions: the K-values are given at the drum temperature and pressure and do not depend on composition (ideal
mixtures, as in the spec); the drum runs at the feed temperature and pressure; no reaction.

Sources: H. H. Rachford Jr. and J. D. Rice, "Procedure for use of electronic digital computers in calculating flash
vaporization hydrocarbon equilibrium", Journal of Petroleum Technology 4(10), 1952 (the equation f(psi) = 0);
J. D. Seader, E. J. Henley and D. K. Roper, Separation Process Principles, ch. 4 (single equilibrium stages and
flash calculations: the isothermal flash, bubble- and dew-point tests).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from process_sim_lab.streams import Stream

TWO_PHASE = "two-phase"
LIQUID = "liquid"
VAPOUR = "vapour"


@dataclass(frozen=True)
class FlashResult:
    """Outlet streams and key numbers of the flash drum.

    Attributes:
        vapour: vapour outlet, mol/s by component; all zero when no vapour forms.
        liquid: liquid outlet, mol/s by component; all zero when no liquid forms.
        vapour_fraction: psi = V / F, in [0, 1].
        x: liquid mole fractions.
        y: vapour mole fractions.
        phase: "two-phase", "liquid" (psi = 0) or "vapour" (psi = 1).
        iterations: bisection steps taken; 0 for a single-phase result.

    When one phase is absent, its composition is the incipient-phase composition (y_i = K_i z_i / sum K_j z_j for an
    all-liquid feed, x_i = (z_i / K_i) / sum (z_j / K_j) for an all-vapour feed). It equals the bubble- or dew-point
    composition when the feed sits exactly at that point.
    """

    vapour: Stream
    liquid: Stream
    vapour_fraction: float
    x: dict[str, float]
    y: dict[str, float]
    phase: str
    iterations: int


def rachford_rice(z: dict[str, float], k_values: dict[str, float], psi: float) -> float:
    """Rachford-Rice function f(psi) = sum_i z_i (K_i - 1) / (1 + psi (K_i - 1))."""
    return sum(zi * (k_values[c] - 1.0) / (1.0 + psi * (k_values[c] - 1.0)) for c, zi in z.items())


def isothermal_flash(
    feed: Stream,
    *,
    k_values: dict[str, float],
    tol: float = 1e-12,
    max_iter: int = 200,
) -> FlashResult:
    """Flash a feed at fixed temperature and pressure with given K-values.

    Args:
        feed: inlet stream, total flow > 0. The drum runs at its temperature and pressure.
        k_values: K_i = y_i / x_i at drum conditions, > 0 and finite, for every component with a positive flow.
            Entries for other components are ignored; components with zero flow leave with zero flow.
        tol: bisection stops when the bracket on psi is narrower than this, > 0.
        max_iter: upper limit on bisection steps, >= 1.

    Returns:
        FlashResult with the vapour and liquid outlets (feed T and P), psi = V / F, x, y, the phase label and the
        number of bisection steps.
    """
    if tol <= 0:
        raise ValueError(f"tol must be > 0, got {tol}")
    if max_iter < 1:
        raise ValueError(f"max_iter must be >= 1, got {max_iter}")
    total = feed.total_flow
    if total <= 0:
        raise ValueError("feed has no flow")

    present = {c: f for c, f in feed.flows.items() if f > 0}
    for c in present:
        if c not in k_values:
            raise ValueError(f"no K-value for component {c!r}")
        k = k_values[c]
        if not math.isfinite(k) or k <= 0:
            raise ValueError(f"K-value of {c!r} must be finite and > 0, got {k}")
    z = {c: f / total for c, f in present.items()}
    k = {c: k_values[c] for c in present}

    iterations = 0
    if sum(z[c] * k[c] for c in z) - 1.0 <= 0.0:
        psi, phase = 0.0, LIQUID
    elif 1.0 - sum(z[c] / k[c] for c in z) >= 0.0:
        psi, phase = 1.0, VAPOUR
    else:
        lo, hi = 0.0, 1.0  # f(lo) > 0 > f(hi)
        while hi - lo > tol and iterations < max_iter:
            mid = 0.5 * (lo + hi)
            if mid in (lo, hi):  # bracket at float resolution
                break
            iterations += 1
            if rachford_rice(z, k, mid) > 0.0:
                lo = mid
            else:
                hi = mid
        psi, phase = 0.5 * (lo + hi), TWO_PHASE

    if phase == LIQUID:
        x = dict(z)
        bubble = sum(z[c] * k[c] for c in z)
        y = {c: z[c] * k[c] / bubble for c in z}
    elif phase == VAPOUR:
        y = dict(z)
        dew = sum(z[c] / k[c] for c in z)
        x = {c: z[c] / k[c] / dew for c in z}
    else:
        x = {c: z[c] / (1.0 + psi * (k[c] - 1.0)) for c in z}
        y = {c: k[c] * x[c] for c in z}

    vapour_flows = {c: 0.0 for c in feed.flows}
    liquid_flows = {c: 0.0 for c in feed.flows}
    for c, f in present.items():
        if phase == LIQUID:
            liquid_flows[c] = f
        elif phase == VAPOUR:
            vapour_flows[c] = f
        else:
            liquid_flows[c] = f * (1.0 - psi) / (1.0 + psi * (k[c] - 1.0))
            vapour_flows[c] = max(0.0, f - liquid_flows[c])  # guard a -1 ulp rounding at psi near 0

    for c in feed.flows:
        x.setdefault(c, 0.0)
        y.setdefault(c, 0.0)

    state = dict(temperature=feed.temperature, pressure=feed.pressure)
    return FlashResult(
        vapour=Stream(flows=vapour_flows, **state),
        liquid=Stream(flows=liquid_flows, **state),
        vapour_fraction=psi,
        x=x,
        y=y,
        phase=phase,
        iterations=iterations,
    )
