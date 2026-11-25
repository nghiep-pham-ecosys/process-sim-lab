# Splitter

One inlet stream divides into several outlets of the same composition.

Code: [`src/process_sim_lab/units/splitter.py`](../../src/process_sim_lab/units/splitter.py) ·
tests: [`tests/test_splitter.py`](../../tests/test_splitter.py)

## Model

Steady state, no reaction, no phase change:

```text
split fractions      s_j >= 0,  sum over outlets j of s_j = 1
mole balance         F_i,j = s_j * F_i,in      for every component i   [mol/s]
state                T_j = T_in,  P_j = P_in
```

Every outlet has the inlet composition, temperature and pressure; only the total flow differs. The fractions must sum
to 1 within 1e-9, so the outlets add back to the inlet.

## Example

A purge of one quarter and a recycle of three quarters:

```python
from process_sim_lab import Stream
from process_sim_lab.units import split_stream

purge, recycle = split_stream(Stream(flows={"A": 6.0, "B": 4.0}), [0.25, 0.75])
print(purge.flows, recycle.flows)    # {'A': 1.5, 'B': 1.0} {'A': 4.5, 'B': 3.0}
assert purge.flows == {"A": 1.5, "B": 1.0} and recycle.flows == {"A": 4.5, "B": 3.0}
```

## In a flowsheet and as a tool

- Flowsheet unit type `splitter`, one inlet and one outlet per fraction. Param: `fractions`. Nothing to size.
- Agent tool `splitter` (see [Agent layer and MCP](../agent.md)).

## Source

R. M. Felder and R. W. Rousseau, *Elementary Principles of Chemical Processes*, ch. 4 (balances on non-reactive
processes and on splitting points).
