"""Mixer: several inlet streams join into one outlet, no reaction.

Model (steady state, no accumulation, no reaction):

    mole balance per component  F_i,out = sum over inlets j of F_i,j      [mol/s]
    total                       F_out   = sum over inlets j of F_j
    pressure                    P_out   = min over inlets j of P_j

Assumptions: the outlet pressure is the lowest inlet pressure (streams can only mix at the lowest pressure without
a pump or compressor). No energy balance yet: the library has no heat capacities, so the outlet temperature is
either the common inlet temperature, or a value the caller states (for example from an energy balance done
elsewhere). Inlets at different temperatures without a stated outlet temperature are rejected.
Source: R. M. Felder and R. W. Rousseau, Elementary Principles of Chemical Processes, ch. 4 (fundamentals of
material balances: balances on non-reactive processes and on mixing points). The tests use hand-summed flows.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from process_sim_lab.streams import Stream


def mix_streams(inlets: Sequence[Stream], *, temperature: float | None = None) -> Stream:
    """Mix inlet streams into one outlet stream.

    Args:
        inlets: one or more inlet streams.
        temperature: outlet temperature, K. If None, all inlets must have the same temperature and the outlet
            takes it.

    Returns:
        The outlet stream: component flows summed over the inlets (components in first-seen order), the lowest
        inlet pressure, and the common inlet temperature or the stated ``temperature``.
    """
    if not inlets:
        raise ValueError("a mixer needs at least one inlet stream")

    if temperature is None:
        first = inlets[0].temperature
        for s in inlets[1:]:
            if not math.isclose(s.temperature, first, rel_tol=1e-12, abs_tol=1e-9):
                raise ValueError(
                    f"inlet temperatures differ ({first} K and {s.temperature} K); "
                    "pass the outlet temperature explicitly"
                )
        temperature = first

    flows: dict[str, float] = {}
    for s in inlets:
        for name, value in s.flows.items():
            flows[name] = flows.get(name, 0.0) + value

    pressure = min(s.pressure for s in inlets)
    return Stream(flows=flows, temperature=temperature, pressure=pressure)
