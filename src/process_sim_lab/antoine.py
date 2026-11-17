"""Pure-component vapour pressure from the Antoine equation.

Model (the form used by the NIST Chemistry WebBook):

    log10(P / bar) = A - B / (T / K + C)

    vapour pressure      P_sat(T) = 1e5 * 10 ** (A - B / (T + C))         [Pa]
    saturation temp.     T_sat(P) = B / (A - log10(P / 1e5)) - C           [K]

A is dimensionless, B is in K and C is in K. The constants are kept exactly as published (bar, K); the functions
take and return SI units (K, Pa) and convert only at that edge.

Assumptions: a pure liquid in equilibrium with its own vapour; the fit is used only inside the temperature range of
the data it was fitted to. Outside that range the functions raise ValueError instead of extrapolating.

Source of every constant set: NIST Chemistry WebBook, NIST Standard Reference Database 69, "Phase change data",
table "Antoine Equation Parameters" for each compound (https://webbook.nist.gov/chemistry/, accessed 2026-11-17).
All three sets below come from the row the WebBook attributes to "Williamham, Taylor, et al., 1945".
"""

from __future__ import annotations

import math
from dataclasses import dataclass

PA_PER_BAR = 1e5


@dataclass(frozen=True)
class AntoineConstants:
    """One Antoine fit in the NIST form log10(P / bar) = A - B / (T / K + C).

    Attributes:
        a: A, dimensionless.
        b: B, K.
        c: C, K.
        t_min: lowest temperature of the fitted data, K.
        t_max: highest temperature of the fitted data, K.
        source: where the constants come from.
    """

    a: float
    b: float
    c: float
    t_min: float
    t_max: float
    source: str

    def __post_init__(self) -> None:
        if self.b <= 0:
            raise ValueError(f"B must be > 0 K, got {self.b}")
        if not 0 < self.t_min < self.t_max:
            raise ValueError(f"need 0 < t_min < t_max, got {self.t_min} and {self.t_max}")
        if self.t_min + self.c <= 0:
            raise ValueError("T + C must stay > 0 over the valid range")

    def _check_range(self, temperature: float) -> None:
        if not self.t_min <= temperature <= self.t_max:
            raise ValueError(
                f"temperature {temperature} K is outside the fitted range {self.t_min} to {self.t_max} K"
            )

    def vapour_pressure(self, temperature: float) -> float:
        """Vapour pressure in Pa at ``temperature`` in K (inside the fitted range)."""
        self._check_range(temperature)
        return PA_PER_BAR * 10.0 ** (self.a - self.b / (temperature + self.c))

    def saturation_temperature(self, pressure: float) -> float:
        """Saturation (boiling) temperature in K at ``pressure`` in Pa; the result must lie in the fitted range."""
        if pressure <= 0:
            raise ValueError(f"pressure must be > 0 Pa, got {pressure}")
        denominator = self.a - math.log10(pressure / PA_PER_BAR)
        if denominator <= 0:
            raise ValueError(f"pressure {pressure} Pa is beyond this fit")
        temperature = self.b / denominator - self.c
        self._check_range(temperature)
        return temperature


_NIST = "NIST Chemistry WebBook (SRD 69), Antoine Equation Parameters; data of Williamham, Taylor, et al., 1945"

ANTOINE: dict[str, AntoineConstants] = {
    # NIST WebBook, benzene (CAS 71-43-2), row 287.70 to 354.07 K.
    "benzene": AntoineConstants(a=4.01814, b=1203.835, c=-53.226, t_min=287.70, t_max=354.07, source=_NIST),
    # NIST WebBook, toluene (CAS 108-88-3), row 308.52 to 384.66 K.
    "toluene": AntoineConstants(a=4.07827, b=1343.943, c=-53.773, t_min=308.52, t_max=384.66, source=_NIST),
    # NIST WebBook, ethylbenzene (CAS 100-41-4), row 329.74 to 410.27 K.
    "ethylbenzene": AntoineConstants(a=4.07488, b=1419.315, c=-60.539, t_min=329.74, t_max=410.27, source=_NIST),
}


def _constants(component: str) -> AntoineConstants:
    try:
        return ANTOINE[component]
    except KeyError:
        known = ", ".join(sorted(ANTOINE))
        raise ValueError(f"no Antoine constants for {component!r}; known: {known}") from None


def vapour_pressure(component: str, temperature: float) -> float:
    """Vapour pressure of a pure component, Pa.

    Args:
        component: a key of ``ANTOINE`` (for example ``"benzene"``).
        temperature: K, inside the fitted range of that component.
    """
    return _constants(component).vapour_pressure(temperature)


def saturation_temperature(component: str, pressure: float) -> float:
    """Boiling temperature of a pure component at ``pressure``, K.

    Args:
        component: a key of ``ANTOINE``.
        pressure: Pa, > 0; the answer must fall inside the fitted range.
    """
    return _constants(component).saturation_temperature(pressure)
