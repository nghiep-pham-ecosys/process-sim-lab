"""Material streams.

A stream holds molar flows by component (mol/s), temperature (K) and pressure (Pa). SI units throughout.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Stream:
    """A steady-state material stream.

    Attributes:
        flows: molar flow of each component, mol/s. Values must be >= 0.
        temperature: K, > 0.
        pressure: Pa, > 0.
    """

    flows: dict[str, float] = field(default_factory=dict)
    temperature: float = 298.15
    pressure: float = 101_325.0

    def __post_init__(self) -> None:
        for name, value in self.flows.items():
            if value < 0:
                raise ValueError(f"flow of {name!r} is negative: {value}")
        if self.temperature <= 0:
            raise ValueError(f"temperature must be > 0 K, got {self.temperature}")
        if self.pressure <= 0:
            raise ValueError(f"pressure must be > 0 Pa, got {self.pressure}")

    @property
    def total_flow(self) -> float:
        """Total molar flow, mol/s."""
        return sum(self.flows.values())

    def mole_fraction(self, component: str) -> float:
        """Mole fraction of one component; 0 for an empty stream or a missing component."""
        total = self.total_flow
        if total == 0:
            return 0.0
        return self.flows.get(component, 0.0) / total
