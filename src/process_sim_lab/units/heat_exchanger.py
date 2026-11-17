"""Counter-current heat exchanger sized by the log mean temperature difference (LMTD).

Model (steady state, terminal temperatures known):

    terminal differences   dT1 = T_hot,in  - T_cold,out                    [K]
                           dT2 = T_hot,out - T_cold,in                     [K]
    log mean difference    LMTD = (dT1 - dT2) / ln(dT1 / dT2)              [K]
    equal-difference limit LMTD -> dT1 = dT2   as dT1 / dT2 -> 1
    rate equation          Q = U * A * LMTD  =>  A = Q / (U * LMTD)        [m2]

Assumptions: pure counter-current flow (no F correction factor), constant overall coefficient U along the exchanger,
constant specific heats, no heat loss to the surroundings, no phase change inside the exchanger.
Source: F. P. Incropera, D. P. DeWitt et al., Fundamentals of Heat and Mass Transfer, ch. 11 (heat exchangers,
log mean temperature difference method for the counterflow exchanger).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Below this relative gap between dT1 and dT2 the arithmetic mean is used. Its relative error against the true
# LMTD is about (ln(dT1/dT2))**2 / 12, under 1e-13 here, while the log form would lose digits to round-off.
_EQUAL_DT_REL_TOL = 1e-6


@dataclass(frozen=True)
class HeatExchangerResult:
    """Area and key numbers of a counter-current exchanger."""

    area: float
    lmtd: float
    delta_t1: float
    delta_t2: float


def log_mean_temperature_difference(delta_t1: float, delta_t2: float) -> float:
    """LMTD of two terminal temperature differences, K.

    Both differences must be > 0. When they are equal (or nearly so) the limit value is returned instead of 0/0.
    """
    if delta_t1 <= 0 or delta_t2 <= 0:
        raise ValueError(f"terminal temperature differences must be > 0 K, got {delta_t1} and {delta_t2}")
    if abs(delta_t1 - delta_t2) <= _EQUAL_DT_REL_TOL * max(delta_t1, delta_t2):
        return 0.5 * (delta_t1 + delta_t2)
    return (delta_t1 - delta_t2) / math.log(delta_t1 / delta_t2)


def counter_current_area(
    *,
    duty: float,
    overall_u: float,
    hot_in: float,
    hot_out: float,
    cold_in: float,
    cold_out: float,
) -> HeatExchangerResult:
    """Heat-transfer area of a counter-current exchanger, A = Q / (U * LMTD).

    Args:
        duty: heat duty Q, W, > 0.
        overall_u: overall heat-transfer coefficient U, W/(m2 K), > 0.
        hot_in: hot-side inlet temperature, K.
        hot_out: hot-side outlet temperature, K; <= hot_in.
        cold_in: cold-side inlet temperature, K.
        cold_out: cold-side outlet temperature, K; >= cold_in.

    Returns:
        HeatExchangerResult with the area (m2), the LMTD (K) and the terminal differences dT1 and dT2 (K).

    Raises:
        ValueError: on a non-positive duty or U, a hot side that heats up, a cold side that cools down, or a
        temperature cross (a terminal difference <= 0).
    """
    if duty <= 0:
        raise ValueError(f"duty must be > 0 W, got {duty}")
    if overall_u <= 0:
        raise ValueError(f"overall_u must be > 0 W/(m2 K), got {overall_u}")
    for name, value in (("hot_in", hot_in), ("hot_out", hot_out), ("cold_in", cold_in), ("cold_out", cold_out)):
        if value <= 0:
            raise ValueError(f"{name} must be > 0 K, got {value}")
    if hot_out > hot_in:
        raise ValueError(f"hot side must cool: hot_out {hot_out} K > hot_in {hot_in} K")
    if cold_out < cold_in:
        raise ValueError(f"cold side must heat: cold_out {cold_out} K < cold_in {cold_in} K")

    delta_t1 = hot_in - cold_out
    delta_t2 = hot_out - cold_in
    if delta_t1 <= 0 or delta_t2 <= 0:
        raise ValueError(f"temperature cross: dT1 = {delta_t1} K, dT2 = {delta_t2} K; both must be > 0")

    lmtd = log_mean_temperature_difference(delta_t1, delta_t2)
    area = duty / (overall_u * lmtd)
    return HeatExchangerResult(area=area, lmtd=lmtd, delta_t1=delta_t1, delta_t2=delta_t2)
