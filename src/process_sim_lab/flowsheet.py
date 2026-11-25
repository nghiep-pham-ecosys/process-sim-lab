"""Sequential-modular flowsheet defined in JSON, with recycle loops solved by tearing.

A flowsheet is a set of feed streams and unit operations joined by named streams. Each stream is produced by at most
one unit and consumed by at most one unit. A stream that no unit produces is a feed; a stream that no unit consumes
is a product. A recycle loop is broken by a tear stream: the solver guesses it, runs every unit once in sequence
(one pass), and compares the guess with the value the pass computes.

Model (steady state, sequential-modular):

    tear variables      x = (F_1, ..., F_n, T, P) of each tear stream            [mol/s, K, Pa]
    one pass            g(x) = tear values computed by running the units in order with the guess x
    fixed point         x* = g(x*)
    scaled residual     r(x) = max_i |g_i(x) - x_i| / max(1, |x_i|)
    converged when      r(x) <= tol   (an absolute tolerance on flows below 1 mol/s, a relative one above)

Two update rules:

    direct substitution x_(k+1) = g(x_k)
    Wegstein            s_i = (g_i(x_k) - g_i(x_(k-1))) / (x_k,i - x_(k-1),i)
                        q_i = s_i / (s_i - 1),  bounded to [q_min, q_max]
                        x_(k+1),i = q_i * x_k,i + (1 - q_i) * g_i(x_k)

Wegstein fits a secant to each tear variable separately. For a variable that responds linearly, g_i = a x_i + b,
the step lands on the fixed point b / (1 - a) at once. The first step is direct substitution, since the secant needs
two points. A variable that did not move (x_k,i = x_(k-1),i) takes q_i = 0, a plain substitution. The default
bounds [-5, 0] allow acceleration (q < 0) but no damping. After each step, flows below zero are set to zero and a
temperature or pressure that would drop to zero or below takes its substituted value g_i(x_k).

Each pass runs the units in a calculation order found by a topological sort of the units with the tear streams cut.
A loop with no tear stream is rejected with the units that form it. The loop stops with ConvergenceError when the
residual is still above tol after max_iter passes, or when a tear variable is not finite. The default tol, 1e-10,
sits above the resolution of the flash's own bisection (1e-12 on psi by default); a much tighter tol can stall on
that noise.

A tear stream without an "initial" guess starts at zero flow. That suits a tear such as the recycle, whose zero
first guess still leaves the loop units with the fresh feed. A tear upstream of a unit that needs flow, such as a
flash fed by the tear directly or through other units, gives that unit an empty feed on the first pass: the pass fails
with a ValueError that names the unit and the unguessed tear streams. Give such a tear stream an "initial" guess.

JSON form (all numbers in SI units: mol/s, K, Pa, m3, m3/s, 1/s):

    {
      "name": "reactor-flash-recycle",
      "feeds": {"feed": {"flows": {"A": 5.6, "I": 2.4}, "temperature": 330.0, "pressure": 200000.0}},
      "units": [
        {"name": "mixer", "type": "mixer", "inlets": ["feed", "recycle"], "outlets": ["reactor-in"]},
        {"name": "reactor", "type": "cstr", "inlets": ["reactor-in"], "outlets": ["reactor-out"],
         "params": {"reactant": "A", "product": "B", "rate_constant": 0.023, "volume": 2.0, "volumetric_flow": 0.02}},
        ...
      ],
      "tear": {"streams": ["recycle"], "method": "wegstein", "tol": 1e-10, "max_iter": 100}
    }

A stream has "flows" and optional "temperature" and "pressure" (Stream defaults otherwise). A unit's "params" are the
keyword arguments of its model: mixer (temperature), splitter (fractions), cstr and pfr (reactant, product,
rate_constant, volume, volumetric_flow), flash (k_values, tol, max_iter). A flash has two outlets, vapour then liquid;
a splitter has one outlet per fraction. "tear" may also hold "initial" (a first guess per tear stream) and "q_min",
"q_max". Unknown keys are rejected, so a misspelt name fails loudly instead of being ignored.

Assumptions: the unit models of this library (isothermal, no energy balance); every stream carries the flows of all
components of the flowsheet, zero where absent. The tear stream in the result is the last guess x, the value every
unit downstream of it saw, so the unit that produces it closes its balance to within the residual.

Sources: R. M. Felder and R. W. Rousseau, Elementary Principles of Chemical Processes, ch. 4 (material balances on
multiple-unit processes, recycle and purge); A. W. Westerberg, H. P. Hutchison, R. L. Motard and P. Winter, Process
Flowsheeting, Cambridge University Press, 1979 (sequential-modular simulation, tear streams, convergence of recycle
loops); J. H. Wegstein, "Accelerating convergence of iterative processes", Communications of the ACM 1(6), 1958
(the secant update; the bounds on q are a safeguard added in flowsheeting practice, not part of that paper).
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from process_sim_lab.streams import Stream
from process_sim_lab.units.cstr import isothermal_cstr_first_order
from process_sim_lab.units.flash import isothermal_flash
from process_sim_lab.units.mixer import mix_streams
from process_sim_lab.units.pfr import isothermal_pfr_first_order
from process_sim_lab.units.splitter import split_stream

DIRECT = "direct"
WEGSTEIN = "wegstein"
METHODS = (DIRECT, WEGSTEIN)


class ConvergenceError(RuntimeError):
    """The tear loop did not converge.

    Attributes:
        iterations: passes run.
        residual: scaled residual of the last pass (may be inf or nan when the loop diverged).
    """

    def __init__(self, message: str, *, iterations: int, residual: float) -> None:
        super().__init__(message)
        self.iterations = iterations
        self.residual = residual


# ---------------------------------------------------------------------------------------------------------------------
# Unit handlers: (unit spec, inlet streams) -> (outlet streams, generation by component in mol/s)
# ---------------------------------------------------------------------------------------------------------------------

Handler = Callable[["UnitSpec", list[Stream]], tuple[list[Stream], dict[str, float]]]


def _run_mixer(unit: UnitSpec, inlets: list[Stream]) -> tuple[list[Stream], dict[str, float]]:
    return [mix_streams(inlets, temperature=unit.params.get("temperature"))], {}


def _run_splitter(unit: UnitSpec, inlets: list[Stream]) -> tuple[list[Stream], dict[str, float]]:
    return split_stream(inlets[0], unit.params["fractions"]), {}


def _reactor(solve: Callable[..., Any]) -> Handler:
    def run(unit: UnitSpec, inlets: list[Stream]) -> tuple[list[Stream], dict[str, float]]:
        p = unit.params
        result = solve(
            inlets[0],
            reactant=p["reactant"],
            product=p["product"],
            rate_constant=p["rate_constant"],
            volume=p["volume"],
            volumetric_flow=p["volumetric_flow"],
        )
        extent = inlets[0].flows[p["reactant"]] - result.outlet.flows[p["reactant"]]
        return [result.outlet], {p["reactant"]: -extent, p["product"]: extent}

    return run


def _run_flash(unit: UnitSpec, inlets: list[Stream]) -> tuple[list[Stream], dict[str, float]]:
    options = {k: unit.params[k] for k in ("tol", "max_iter") if k in unit.params}
    result = isothermal_flash(inlets[0], k_values=unit.params["k_values"], **options)
    return [result.vapour, result.liquid], {}


_REACTOR_PARAMS = frozenset({"reactant", "product", "rate_constant", "volume", "volumetric_flow"})


@dataclass(frozen=True)
class _UnitType:
    handler: Handler
    required: frozenset[str]
    optional: frozenset[str]
    many_inlets: bool  # True: one or more inlets; False: exactly one


UNIT_TYPES: dict[str, _UnitType] = {
    "mixer": _UnitType(_run_mixer, frozenset(), frozenset({"temperature"}), True),
    "splitter": _UnitType(_run_splitter, frozenset({"fractions"}), frozenset(), False),
    "cstr": _UnitType(_reactor(isothermal_cstr_first_order), _REACTOR_PARAMS, frozenset(), False),
    "pfr": _UnitType(_reactor(isothermal_pfr_first_order), _REACTOR_PARAMS, frozenset(), False),
    "flash": _UnitType(_run_flash, frozenset({"k_values"}), frozenset({"tol", "max_iter"}), False),
}


def _outlet_count(unit: UnitSpec) -> int:
    if unit.type == "flash":
        return 2  # vapour, liquid
    if unit.type == "splitter":
        return len(unit.params["fractions"])
    return 1


# ---------------------------------------------------------------------------------------------------------------------
# Flowsheet definition
# ---------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class UnitSpec:
    """One unit operation of a flowsheet.

    Attributes:
        name: unique unit name.
        type: one of UNIT_TYPES ("mixer", "splitter", "cstr", "pfr", "flash").
        inlets: names of the inlet streams, in order.
        outlets: names of the outlet streams, in order (a flash: vapour, then liquid; a splitter: one per fraction).
        params: keyword arguments of the unit model.
    """

    name: str
    type: str
    inlets: tuple[str, ...]
    outlets: tuple[str, ...]
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TearSettings:
    """How the recycle loops are converged.

    Attributes:
        streams: names of the tear streams; empty for a flowsheet without recycle.
        initial: first guess of each tear stream. A tear stream without one starts at zero flow, at the temperature
            and pressure of the first feed; a tear that feeds a flash, directly or through other units, needs one.
        method: "wegstein" (default) or "direct".
        tol: tolerance on the scaled residual, > 0.
        max_iter: most passes allowed, >= 1.
        q_min, q_max: bounds on the Wegstein q, q_min <= q_max < 1.
    """

    streams: tuple[str, ...] = ()
    initial: Mapping[str, Stream] = field(default_factory=dict)
    method: str = WEGSTEIN
    tol: float = 1e-10
    max_iter: int = 100
    q_min: float = -5.0
    q_max: float = 0.0

    def __post_init__(self) -> None:
        if self.method not in METHODS:
            raise ValueError(f"tear method must be one of {list(METHODS)}, got {self.method!r}")
        if not (isinstance(self.tol, (int, float)) and math.isfinite(self.tol) and self.tol > 0):
            raise ValueError(f"tear tol must be finite and > 0, got {self.tol!r}")
        if not isinstance(self.max_iter, int) or isinstance(self.max_iter, bool) or self.max_iter < 1:
            raise ValueError(f"tear max_iter must be an integer >= 1, got {self.max_iter!r}")
        if not self.q_min <= self.q_max < 1.0:
            raise ValueError(f"need q_min <= q_max < 1, got {self.q_min} and {self.q_max}")
        if len(set(self.streams)) != len(self.streams):
            raise ValueError(f"tear streams repeat a name: {list(self.streams)}")
        for name in self.initial:
            if name not in self.streams:
                raise ValueError(f"initial guess given for {name!r}, which is not a tear stream")


@dataclass(frozen=True)
class Flowsheet:
    """A checked flowsheet, ready to solve. Build it with ``Flowsheet.from_dict``, ``from_json`` or ``load``.

    Attributes:
        name: flowsheet name.
        feeds: feed streams by name.
        units: unit operations, in the order given.
        tear: tear streams and solver settings.
        order: unit names in calculation order.
        products: names of the streams no unit consumes.
        components: every component of the flowsheet, in first-seen order.
    """

    name: str
    feeds: Mapping[str, Stream]
    units: tuple[UnitSpec, ...]
    tear: TearSettings
    order: tuple[str, ...]
    products: tuple[str, ...]
    components: tuple[str, ...]

    @classmethod
    def build(
        cls,
        *,
        feeds: Mapping[str, Stream],
        units: Sequence[UnitSpec],
        tear: TearSettings | None = None,
        name: str = "flowsheet",
    ) -> Flowsheet:
        """Check the connections and find the calculation order."""
        tear = tear or TearSettings()
        units = tuple(units)
        if not feeds:
            raise ValueError("a flowsheet needs at least one feed stream")
        if not units:
            raise ValueError("a flowsheet needs at least one unit")

        names = [u.name for u in units]
        if len(set(names)) != len(names):
            raise ValueError(f"unit names repeat: {names}")

        producer: dict[str, str] = {}
        consumer: dict[str, str] = {}
        for u in units:
            _check_unit(u)
            for s in u.outlets:
                if s in feeds:
                    raise ValueError(f"stream {s!r} is a feed and also an outlet of unit {u.name!r}")
                if s in producer:
                    raise ValueError(f"stream {s!r} is an outlet of both {producer[s]!r} and {u.name!r}")
                producer[s] = u.name
            for s in u.inlets:
                if s in consumer:
                    raise ValueError(f"stream {s!r} is an inlet of both {consumer[s]!r} and {u.name!r}")
                consumer[s] = u.name

        for u in units:
            for s in u.inlets:
                if s not in feeds and s not in producer:
                    raise ValueError(f"inlet {s!r} of unit {u.name!r} is neither a feed nor an outlet of a unit")
        for s in feeds:
            if s not in consumer:
                raise ValueError(f"feed {s!r} is not an inlet of any unit")
        for s in tear.streams:
            if s not in producer or s not in consumer:
                raise ValueError(f"tear stream {s!r} must be an outlet of one unit and an inlet of another")

        order = _calculation_order(units, producer, consumer, set(tear.streams))
        products = tuple(s for u in units for s in u.outlets if s not in consumer)

        components: dict[str, None] = {}
        for stream in (*feeds.values(), *tear.initial.values()):
            components.update(dict.fromkeys(stream.flows))
        for u in units:
            if u.type in ("cstr", "pfr"):
                components.update(dict.fromkeys((u.params["reactant"], u.params["product"])))

        return cls(
            name=name,
            feeds=dict(feeds),
            units=units,
            tear=tear,
            order=order,
            products=products,
            components=tuple(components),
        )

    @classmethod
    def from_dict(cls, spec: Mapping[str, Any]) -> Flowsheet:
        """Build a flowsheet from its JSON form (the format is in the module docstring)."""
        if not isinstance(spec, Mapping):
            raise ValueError("a flowsheet spec must be a JSON object")
        _check_keys("flowsheet", spec, required={"feeds", "units"}, optional={"name", "tear"})

        feeds_spec = spec["feeds"]
        if not isinstance(feeds_spec, Mapping):
            raise ValueError("'feeds' must be an object of streams by name")
        feeds = {name: _stream_from_dict(f"feed {name!r}", s) for name, s in feeds_spec.items()}

        units_spec = spec["units"]
        if not isinstance(units_spec, list):
            raise ValueError("'units' must be a list")
        units = [_unit_from_dict(i, u) for i, u in enumerate(units_spec)]

        tear = _tear_from_dict(spec.get("tear", {}))
        name = spec.get("name", "flowsheet")
        if not isinstance(name, str):
            raise ValueError("'name' must be a string")
        return cls.build(feeds=feeds, units=units, tear=tear, name=name)

    @classmethod
    def from_json(cls, text: str) -> Flowsheet:
        """Build a flowsheet from a JSON string."""
        return cls.from_dict(json.loads(text))

    @classmethod
    def load(cls, path: str | Path) -> Flowsheet:
        """Build a flowsheet from a JSON file."""
        return cls.from_json(Path(path).read_text(encoding="utf-8"))


def _check_keys(where: str, obj: Mapping[str, Any], *, required: set[str], optional: set[str]) -> None:
    missing = required - obj.keys()
    if missing:
        raise ValueError(f"{where}: missing {sorted(missing)}")
    unknown = obj.keys() - required - optional
    if unknown:
        raise ValueError(f"{where}: unknown keys {sorted(unknown)}; allowed {sorted(required | optional)}")


def _stream_from_dict(where: str, obj: Any) -> Stream:
    if not isinstance(obj, Mapping):
        raise ValueError(f"{where}: a stream must be an object")
    _check_keys(where, obj, required={"flows"}, optional={"temperature", "pressure"})
    flows = obj["flows"]
    if not isinstance(flows, Mapping):
        raise ValueError(f"{where}: 'flows' must be an object of mol/s by component")
    for c, v in flows.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"{where}: flow of {c!r} must be a finite number, got {v!r}")
    state = {k: float(obj[k]) for k in ("temperature", "pressure") if k in obj}
    return Stream(flows={c: float(v) for c, v in flows.items()}, **state)


def _unit_from_dict(index: int, obj: Any) -> UnitSpec:
    where = f"unit {index}"
    if not isinstance(obj, Mapping):
        raise ValueError(f"{where}: a unit must be an object")
    _check_keys(where, obj, required={"name", "type", "inlets", "outlets"}, optional={"params"})
    for key in ("inlets", "outlets"):
        if not isinstance(obj[key], list) or not all(isinstance(s, str) for s in obj[key]):
            raise ValueError(f"{where}: {key!r} must be a list of stream names")
    params = obj.get("params", {})
    if not isinstance(params, Mapping):
        raise ValueError(f"{where}: 'params' must be an object")
    return UnitSpec(
        name=str(obj["name"]),
        type=str(obj["type"]),
        inlets=tuple(obj["inlets"]),
        outlets=tuple(obj["outlets"]),
        params=dict(params),
    )


_TEAR_SETTINGS = ("method", "tol", "max_iter", "q_min", "q_max")


def _tear_from_dict(obj: Any) -> TearSettings:
    if not isinstance(obj, Mapping):
        raise ValueError("'tear' must be an object")
    _check_keys("tear", obj, required=set(), optional={"streams", "initial", *_TEAR_SETTINGS})
    streams = obj.get("streams", [])
    if not isinstance(streams, list) or not all(isinstance(s, str) for s in streams):
        raise ValueError("tear: 'streams' must be a list of stream names")
    initial_spec = obj.get("initial", {})
    if not isinstance(initial_spec, Mapping):
        raise ValueError("tear: 'initial' must be an object of streams by name")
    initial = {name: _stream_from_dict(f"tear initial {name!r}", s) for name, s in initial_spec.items()}
    settings = {k: obj[k] for k in _TEAR_SETTINGS if k in obj}
    return TearSettings(streams=tuple(streams), initial=initial, **settings)


def _check_unit(u: UnitSpec) -> None:
    kind = UNIT_TYPES.get(u.type)
    if kind is None:
        raise ValueError(f"unit {u.name!r}: unknown type {u.type!r}; known types {sorted(UNIT_TYPES)}")
    missing = kind.required - u.params.keys()
    if missing:
        raise ValueError(f"unit {u.name!r} ({u.type}): missing params {sorted(missing)}")
    unknown = u.params.keys() - kind.required - kind.optional
    if unknown:
        raise ValueError(
            f"unit {u.name!r} ({u.type}): unknown params {sorted(unknown)}; "
            f"allowed {sorted(kind.required | kind.optional)}"
        )
    if kind.many_inlets and not u.inlets:
        raise ValueError(f"unit {u.name!r} ({u.type}) needs at least one inlet")
    if not kind.many_inlets and len(u.inlets) != 1:
        raise ValueError(f"unit {u.name!r} ({u.type}) needs exactly one inlet, got {len(u.inlets)}")
    if u.type == "splitter" and not isinstance(u.params["fractions"], (list, tuple)):
        raise ValueError(f"unit {u.name!r} (splitter): 'fractions' must be a list")
    expected = _outlet_count(u)
    if len(u.outlets) != expected:
        raise ValueError(f"unit {u.name!r} ({u.type}) needs {expected} outlets, got {len(u.outlets)}")
    if len(set(u.inlets)) != len(u.inlets) or len(set(u.outlets)) != len(u.outlets):
        raise ValueError(f"unit {u.name!r} names a stream twice")


def _calculation_order(
    units: tuple[UnitSpec, ...], producer: dict[str, str], consumer: dict[str, str], torn: set[str]
) -> tuple[str, ...]:
    """Topological sort (Kahn) of the units with the torn streams cut; ties go to the unit listed first."""
    position = {u.name: i for i, u in enumerate(units)}
    downstream: dict[str, list[str]] = {u.name: [] for u in units}
    indegree = {u.name: 0 for u in units}
    for s, src in producer.items():
        dst = consumer.get(s)
        if dst is None or s in torn:
            continue
        downstream[src].append(dst)
        indegree[dst] += 1

    ready = sorted((n for n, d in indegree.items() if d == 0), key=position.__getitem__)
    order: list[str] = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for m in downstream[n]:
            indegree[m] -= 1
            if indegree[m] == 0:
                ready.append(m)
                ready.sort(key=position.__getitem__)
    if len(order) != len(units):
        loop = [u.name for u in units if indegree[u.name] > 0]
        raise ValueError(f"units {loop} form a recycle loop that no tear stream breaks; name one in 'tear.streams'")
    return tuple(order)


# ---------------------------------------------------------------------------------------------------------------------
# Solving
# ---------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class UnitResult:
    """Inlets, outlets and generation of one unit after the last pass.

    Attributes:
        type: unit type.
        inlets: inlet stream names.
        outlets: outlet stream names.
        generation: net generation by reaction, mol/s by component; empty for a unit without reaction.
    """

    type: str
    inlets: tuple[str, ...]
    outlets: tuple[str, ...]
    generation: dict[str, float]


@dataclass(frozen=True)
class FlowsheetResult:
    """The solved flowsheet.

    Attributes:
        name: flowsheet name.
        streams: every stream by name (feeds, internal streams, tear streams at their last guess, products).
        units: per-unit results by unit name, in calculation order.
        feeds: feed stream names.
        products: product stream names.
        components: every component of the flowsheet.
        method: "direct" or "wegstein".
        iterations: passes run (1 for a flowsheet without tear streams).
        residual: scaled tear residual of the last pass; 0 without tear streams.
        tol: the tolerance the residual met.
        history: scaled residual of every pass.
    """

    name: str
    streams: dict[str, Stream]
    units: dict[str, UnitResult]
    feeds: tuple[str, ...]
    products: tuple[str, ...]
    components: tuple[str, ...]
    method: str
    iterations: int
    residual: float
    tol: float
    history: tuple[float, ...]

    def total_generation(self) -> dict[str, float]:
        """Net generation over all units, mol/s by component."""
        total = dict.fromkeys(self.components, 0.0)
        for u in self.units.values():
            for c, g in u.generation.items():
                total[c] += g
        return total

    def unit_balance(self, unit: str) -> dict[str, float]:
        """Mole balance of one unit, in + generation - out, mol/s by component (zero when it closes)."""
        u = self.units[unit]
        return {
            c: math.fsum(
                [self.streams[s].flows.get(c, 0.0) for s in u.inlets]
                + [u.generation.get(c, 0.0)]
                + [-self.streams[s].flows.get(c, 0.0) for s in u.outlets]
            )
            for c in self.components
        }

    def overall_balance(self) -> dict[str, float]:
        """Mole balance of the whole flowsheet, feeds + generation - products, mol/s by component."""
        gen = self.total_generation()
        return {
            c: math.fsum(
                [self.streams[s].flows.get(c, 0.0) for s in self.feeds]
                + [gen[c]]
                + [-self.streams[s].flows.get(c, 0.0) for s in self.products]
            )
            for c in self.components
        }

    def to_dict(self) -> dict[str, Any]:
        """Plain JSON-ready form of the result; ``process_sim_lab.flowsheet_json.RESULT_SCHEMA`` describes it."""
        return {
            "name": self.name,
            "method": self.method,
            "iterations": self.iterations,
            "residual": self.residual,
            "tol": self.tol,
            "history": list(self.history),
            "feeds": list(self.feeds),
            "products": list(self.products),
            "components": list(self.components),
            "streams": {
                name: {"flows": dict(s.flows), "temperature": s.temperature, "pressure": s.pressure}
                for name, s in self.streams.items()
            },
            "units": {
                name: {
                    "type": u.type,
                    "inlets": list(u.inlets),
                    "outlets": list(u.outlets),
                    "generation": dict(u.generation),
                }
                for name, u in self.units.items()
            },
            "overall_balance": self.overall_balance(),
        }


def _to_vector(streams: Sequence[Stream], components: tuple[str, ...]) -> list[float]:
    vector: list[float] = []
    for s in streams:
        extra = s.flows.keys() - set(components)
        if extra:
            raise ValueError(f"tear stream carries components {sorted(extra)} that the flowsheet does not list")
        vector.extend(s.flows.get(c, 0.0) for c in components)
        vector.extend((s.temperature, s.pressure))
    return vector


def _from_vector(vector: Sequence[float], names: Sequence[str], components: tuple[str, ...]) -> dict[str, Stream]:
    width = len(components) + 2
    out: dict[str, Stream] = {}
    for j, name in enumerate(names):
        chunk = vector[j * width : (j + 1) * width]
        out[name] = Stream(
            flows={c: max(0.0, v) for c, v in zip(components, chunk)},
            temperature=chunk[-2],
            pressure=chunk[-1],
        )
    return out


def _scaled_residual(x: Sequence[float], gx: Sequence[float]) -> float:
    if not x:
        return 0.0
    return max(abs(g - v) / max(1.0, abs(v)) for v, g in zip(x, gx))


def _run_pass(
    fs: Flowsheet, tear_guess: Mapping[str, Stream]
) -> tuple[dict[str, Stream], dict[str, UnitResult], dict[str, Stream]]:
    """Run every unit once. Returns the stream table (tear streams at the guess), unit results and computed tears."""
    by_name = {u.name: u for u in fs.units}
    streams: dict[str, Stream] = {**fs.feeds, **tear_guess}
    computed: dict[str, Stream] = {}
    results: dict[str, UnitResult] = {}
    for name in fs.order:
        u = by_name[name]
        try:
            outlets, generation = UNIT_TYPES[u.type].handler(u, [streams[s] for s in u.inlets])
        except (ValueError, TypeError) as exc:  # a TypeError here is a param of the wrong type, e.g. a string
            raise ValueError(f"unit {u.name!r} ({u.type}): {exc}") from exc
        for s, stream in zip(u.outlets, outlets):
            if s in tear_guess:
                computed[s] = stream
            else:
                streams[s] = stream
        results[name] = UnitResult(type=u.type, inlets=u.inlets, outlets=u.outlets, generation=generation)
    return streams, results, computed


def _wegstein_step(
    x: list[float], gx: list[float], x_prev: list[float], g_prev: list[float], q_min: float, q_max: float
) -> list[float]:
    step: list[float] = []
    for xi, gi, xp, gp in zip(x, gx, x_prev, g_prev):
        dx = xi - xp
        if dx == 0.0:
            q = 0.0
        else:
            s = (gi - gp) / dx
            q = 0.0 if s == 1.0 else s / (s - 1.0)
            q = min(q_max, max(q_min, q))
        step.append(q * xi + (1.0 - q) * gi)
    return step


def solve_flowsheet(
    flowsheet: Flowsheet | Mapping[str, Any],
    *,
    method: str | None = None,
    tol: float | None = None,
    max_iter: int | None = None,
) -> FlowsheetResult:
    """Solve a flowsheet, converging its tear streams.

    Args:
        flowsheet: a Flowsheet, or its JSON form as a dict.
        method: "direct" or "wegstein"; overrides the flowsheet's tear settings when given.
        tol: tolerance on the scaled residual; overrides the tear settings when given.
        max_iter: most passes allowed; overrides the tear settings when given.

    Returns:
        FlowsheetResult with every stream, the per-unit generation, the passes run and the residual history.

    Raises:
        ConvergenceError: the residual is still above tol after max_iter passes, or a tear variable is not finite.
        ValueError: a bad flowsheet, or a unit that rejects its inlet during a pass (its name is in the message).
    """
    fs = flowsheet if isinstance(flowsheet, Flowsheet) else Flowsheet.from_dict(flowsheet)
    overrides = {k: v for k, v in (("method", method), ("tol", tol), ("max_iter", max_iter)) if v is not None}
    t = fs.tear
    if overrides:
        t = TearSettings(
            streams=t.streams,
            initial=t.initial,
            method=overrides.get("method", t.method),
            tol=overrides.get("tol", t.tol),
            max_iter=overrides.get("max_iter", t.max_iter),
            q_min=t.q_min,
            q_max=t.q_max,
        )

    names = t.streams
    first_feed = next(iter(fs.feeds.values()))
    empty = Stream(
        flows=dict.fromkeys(fs.components, 0.0), temperature=first_feed.temperature, pressure=first_feed.pressure
    )
    guess = {s: t.initial[s] if s in t.initial else empty for s in names}
    x = _to_vector([guess[s] for s in names], fs.components)
    width = len(fs.components) + 2
    state_index = {j * width + k for j in range(len(names)) for k in (width - 2, width - 1)}  # T and P

    history: list[float] = []
    x_prev: list[float] | None = None
    g_prev: list[float] | None = None
    unguessed = [s for s in names if s not in t.initial]
    for iteration in range(1, t.max_iter + 1):
        tear_guess = _from_vector(x, names, fs.components)
        try:
            streams, results, computed = _run_pass(fs, tear_guess)
        except ValueError as exc:
            if iteration == 1 and unguessed:
                raise ValueError(
                    f"{exc} (first pass, tear streams {unguessed} start at zero flow; give them an initial guess "
                    "in tear.initial)"
                ) from exc
            raise
        gx = _to_vector([computed[s] for s in names], fs.components)
        residual = _scaled_residual(x, gx)
        history.append(residual)
        if not math.isfinite(residual):
            raise ConvergenceError(
                f"tear loop diverged at pass {iteration} (residual {residual})",
                iterations=iteration,
                residual=residual,
            )
        if residual <= t.tol:
            return FlowsheetResult(
                name=fs.name,
                streams={**streams, **tear_guess},
                units=results,
                feeds=tuple(fs.feeds),
                products=fs.products,
                components=fs.components,
                method=t.method,
                iterations=iteration,
                residual=residual,
                tol=t.tol,
                history=tuple(history),
            )

        if t.method == WEGSTEIN and x_prev is not None and g_prev is not None:
            x_next = _wegstein_step(x, gx, x_prev, g_prev, t.q_min, t.q_max)
        else:
            x_next = list(gx)
        for i, v in enumerate(x_next):
            if i in state_index:
                if not v > 0.0:  # a temperature or pressure must stay > 0
                    x_next[i] = gx[i]
            elif v < 0.0:  # a molar flow cannot be negative
                x_next[i] = 0.0
        if not all(math.isfinite(v) for v in x_next):
            raise ConvergenceError(
                f"tear loop diverged at pass {iteration} (a tear variable is not finite)",
                iterations=iteration,
                residual=residual,
            )
        x_prev, g_prev, x = x, gx, x_next

    raise ConvergenceError(
        f"tear streams {list(names)} did not converge in {t.max_iter} passes with {t.method}: "
        f"scaled residual {history[-1]:.3e} > tol {t.tol:.1e}",
        iterations=t.max_iter,
        residual=history[-1],
    )
