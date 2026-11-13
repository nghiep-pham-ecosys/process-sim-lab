"""Isothermal CSTR with one first-order, irreversible, liquid-phase reaction A -> B.

Model (constant density, steady state, perfect mixing):

    space time        tau = V / Q                       [s]
    mole balance on A F_A0 - F_A - k * C_A * V = 0
    with C_A = F_A / Q  =>  F_A = F_A0 / (1 + k * tau)
    conversion        X = k * tau / (1 + k * tau)

Assumptions: constant volumetric flow Q (liquid, no density change), isothermal, one reaction, B formed 1:1.
Source: H. S. Fogler, Elements of Chemical Reaction Engineering, ch. 5 (design equation of a CSTR,
first-order reaction).
"""

from __future__ import annotations

from dataclasses import dataclass

from process_sim_lab.streams import Stream


@dataclass(frozen=True)
class CSTRResult:
    """Outlet stream and key numbers of the reactor."""

    outlet: Stream
    conversion: float
    space_time: float
    damkohler: float


def isothermal_cstr_first_order(
    feed: Stream,
    *,
    reactant: str,
    product: str,
    rate_constant: float,
    volume: float,
    volumetric_flow: float,
) -> CSTRResult:
    """Solve an isothermal CSTR for A -> B with rate r = k * C_A.

    Args:
        feed: inlet stream; must contain ``reactant``.
        reactant: component name of A.
        product: component name of B.
        rate_constant: k, 1/s, >= 0.
        volume: reactor liquid volume V, m3, > 0.
        volumetric_flow: Q, m3/s, > 0.

    Returns:
        CSTRResult with the outlet stream (same T and P as the feed), conversion X, space time tau and the
        Damkohler number Da = k * tau.
    """
    if rate_constant < 0:
        raise ValueError(f"rate_constant must be >= 0, got {rate_constant}")
    if volume <= 0:
        raise ValueError(f"volume must be > 0, got {volume}")
    if volumetric_flow <= 0:
        raise ValueError(f"volumetric_flow must be > 0, got {volumetric_flow}")
    if reactant not in feed.flows:
        raise ValueError(f"feed has no component {reactant!r}")
    if reactant == product:
        raise ValueError("reactant and product must differ")

    tau = volume / volumetric_flow
    damkohler = rate_constant * tau
    conversion = damkohler / (1.0 + damkohler)

    fa0 = feed.flows[reactant]
    reacted = fa0 * conversion
    flows = dict(feed.flows)
    flows[reactant] = fa0 - reacted
    flows[product] = flows.get(product, 0.0) + reacted

    outlet = Stream(flows=flows, temperature=feed.temperature, pressure=feed.pressure)
    return CSTRResult(outlet=outlet, conversion=conversion, space_time=tau, damkohler=damkohler)
