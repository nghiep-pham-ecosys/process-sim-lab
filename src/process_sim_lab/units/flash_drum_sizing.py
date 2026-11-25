"""Vertical flash drum sized by the Souders-Brown vapour velocity.

Model (steady state; the drum is a vertical cylinder sized so the vapour leaves slowly enough to drop its liquid):

    vapour molar mass        M_V = sum_i y_i * M_i                                   [kg/mol]
    vapour density           rho_V = P * M_V / (R * T)        (ideal gas)            [kg/m3]
    vapour volumetric flow   Q_V = V * R * T / P              (ideal gas)            [m3/s]
    allowed vapour velocity  u_max = K_SB * sqrt((rho_L - rho_V) / rho_V)            [m/s]
    cross-section            A = Q_V / u_max                                         [m2]
    diameter                 D = sqrt(4 * A / pi)                                    [m]
    height                   H = (H / D) * D                                         [m]
    volume                   V_drum = pi * D^2 / 4 * H        (cylinder, heads left out)  [m3]

V is the vapour molar flow (mol/s), T and P the drum temperature and pressure, R = 8.31446261815324 J/(mol K).
K_SB is the Souders-Brown coefficient (m/s): about 0.07 m/s for a vertical drum with a demister pad (Towler and
Sinnott); Wankat gives a correlation in the flow parameter. H / D is a design choice, usually 3 to 5 (Wankat).

Assumptions: ideal-gas vapour; the liquid density is given at drum conditions; the vapour load sets the diameter
(the liquid hold-up is not checked); the vessel heads are not counted in the height or the volume.

Sources: M. Souders Jr. and G. G. Brown, "Design of fractionating columns. I. Entrainment and capacity", Industrial
and Engineering Chemistry 26(1), 1934 (the allowed vapour velocity); P. C. Wankat, Separation Process Engineering,
ch. 2 (size calculation of a vertical flash drum: K_drum, cross-section from the vapour load, H / D from 3 to 5);
G. Towler and R. Sinnott, Chemical Engineering Design, ch. 16 (gas-liquid separators: K about 0.07 m/s with a demister
pad).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from process_sim_lab.streams import Stream

GAS_CONSTANT = 8.31446261815324  # J/(mol K), N_A * k_B, exact in the SI since 2019


@dataclass(frozen=True)
class FlashDrumSize:
    """Dimensions and key numbers of a vertical flash drum.

    Attributes:
        diameter: inside diameter D, m.
        height: tangent-to-tangent height H, m.
        volume: cylinder volume pi D^2 H / 4, m3 (heads left out).
        height_to_diameter: H / D, dimensionless, as given.
        vapour_molar_mass: M_V, kg/mol.
        vapour_density: rho_V, kg/m3.
        vapour_volumetric_flow: Q_V, m3/s.
        max_vapour_velocity: u_max, m/s.
    """

    diameter: float
    height: float
    volume: float
    height_to_diameter: float
    vapour_molar_mass: float
    vapour_density: float
    vapour_volumetric_flow: float
    max_vapour_velocity: float


def _positive(name: str, value: float) -> None:
    if not (math.isfinite(value) and value > 0):
        raise ValueError(f"{name} must be finite and > 0, got {value}")


def size_vertical_flash_drum(
    vapour: Stream,
    *,
    molar_masses: Mapping[str, float],
    liquid_density: float,
    souders_brown_k: float,
    height_to_diameter: float,
) -> FlashDrumSize:
    """Size a vertical flash drum from its vapour outlet.

    Args:
        vapour: vapour leaving the drum, total flow > 0; its temperature and pressure are the drum's.
        molar_masses: M_i, kg/mol, > 0 and finite, for every component with a positive vapour flow. Entries for other
            components are ignored.
        liquid_density: rho_L at drum conditions, kg/m3; must exceed the vapour density.
        souders_brown_k: K_SB, m/s, > 0.
        height_to_diameter: H / D, dimensionless, > 0 (usually 3 to 5).

    Returns:
        FlashDrumSize with D, H, the volume, H / D, and the vapour molar mass, density, volumetric flow and allowed
        velocity.

    Raises:
        ValueError: on a vapour with no flow, a missing or bad molar mass, a non-positive input, or a liquid no
        denser than the vapour.
    """
    _positive("liquid_density", liquid_density)
    _positive("souders_brown_k", souders_brown_k)
    _positive("height_to_diameter", height_to_diameter)
    total = vapour.total_flow
    if total <= 0:
        raise ValueError("vapour has no flow: the vapour load cannot size the drum")
    mass_flow = 0.0
    for c, f in vapour.flows.items():
        if f > 0:
            if c not in molar_masses:
                raise ValueError(f"no molar mass for component {c!r}")
            _positive(f"molar mass of {c!r}", molar_masses[c])
            mass_flow += f * molar_masses[c]

    molar_mass = mass_flow / total
    rt = GAS_CONSTANT * vapour.temperature
    vapour_density = vapour.pressure * molar_mass / rt
    if not liquid_density > vapour_density:
        raise ValueError(
            f"liquid_density {liquid_density} kg/m3 must exceed the vapour density {vapour_density:.6g} kg/m3"
        )
    volumetric_flow = total * rt / vapour.pressure
    max_velocity = souders_brown_k * math.sqrt((liquid_density - vapour_density) / vapour_density)
    diameter = math.sqrt(4.0 * volumetric_flow / (math.pi * max_velocity))
    height = height_to_diameter * diameter
    return FlashDrumSize(
        diameter=diameter,
        height=height,
        volume=math.pi * diameter**2 / 4.0 * height,
        height_to_diameter=height_to_diameter,
        vapour_molar_mass=molar_mass,
        vapour_density=vapour_density,
        vapour_volumetric_flow=volumetric_flow,
        max_vapour_velocity=max_velocity,
    )
