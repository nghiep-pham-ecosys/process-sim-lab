# Mixer

Several inlet streams join into one outlet, with no reaction.

Code: [`src/process_sim_lab/units/mixer.py`](../../src/process_sim_lab/units/mixer.py) ·
tests: [`tests/test_mixer.py`](../../tests/test_mixer.py)

## Model

Steady state, no accumulation, no reaction:

```text
mole balance per component  F_i,out = sum over inlets j of F_i,j      [mol/s]
total                       F_out   = sum over inlets j of F_j
pressure                    P_out   = min over inlets j of P_j
```

Assumptions: the outlet pressure is the lowest inlet pressure (streams can only mix at the lowest pressure without a
pump or compressor). There is no energy balance yet: the outlet temperature is either the common inlet temperature or
a value the caller states. Inlets at different temperatures without a stated outlet temperature are rejected.

## Example

```python
from process_sim_lab import Stream
from process_sim_lab.units import mix_streams

s1 = Stream(flows={"A": 2.0, "B": 1.0}, temperature=300.0, pressure=3e5)
s2 = Stream(flows={"A": 3.0, "C": 4.0}, temperature=300.0, pressure=2e5)
mixed = mix_streams([s1, s2])
print(mixed.flows, mixed.pressure)   # {'A': 5.0, 'B': 1.0, 'C': 4.0} 200000.0
assert mixed.flows == {"A": 5.0, "B": 1.0, "C": 4.0} and mixed.pressure == 2e5
```

## In a flowsheet and as a tool

- Flowsheet unit type `mixer`, one or more inlets and one outlet. Optional param: `temperature` (K). Nothing to size.
- Agent tool `mixer` (see [Agent layer and MCP](../agent.md)).

## Source

R. M. Felder and R. W. Rousseau, *Elementary Principles of Chemical Processes*, ch. 4 (balances on non-reactive
processes and on mixing points).
