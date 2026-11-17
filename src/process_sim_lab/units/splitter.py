"""Splitter: one inlet stream divides into several outlets of the same composition.

Model (steady state, no reaction, no phase change):

    split fractions      s_j >= 0,  sum over outlets j of s_j = 1
    mole balance         F_i,j = s_j * F_i,in      for every component i   [mol/s]
    state                T_j = T_in,  P_j = P_in

Every outlet has the inlet composition, temperature and pressure; only the total flow differs. The fractions must
sum to 1 within 1e-9, so the outlets add back to the inlet.
Source: R. M. Felder and R. W. Rousseau, Elementary Principles of Chemical Processes, ch. 4 (fundamentals of
material balances: balances on non-reactive processes and on splitting points). The tests use hand-multiplied
flows.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from process_sim_lab.streams import Stream


def split_stream(feed: Stream, fractions: Sequence[float]) -> list[Stream]:
    """Split a stream into outlets by split fraction.

    Args:
        feed: inlet stream.
        fractions: split fraction of each outlet, each in [0, 1], summing to 1. One outlet per fraction.

    Returns:
        The outlet streams, in the order of ``fractions``. Each has the feed composition, temperature and
        pressure, and ``fraction * feed`` flow of every component.
    """
    if not fractions:
        raise ValueError("a splitter needs at least one split fraction")
    for j, s in enumerate(fractions):
        if not 0.0 <= s <= 1.0:
            raise ValueError(f"split fraction {j} must be in [0, 1], got {s}")
    total = math.fsum(fractions)
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"split fractions must sum to 1, got {total}")

    return [
        Stream(
            flows={name: s * value for name, value in feed.flows.items()},
            temperature=feed.temperature,
            pressure=feed.pressure,
        )
        for s in fractions
    ]
