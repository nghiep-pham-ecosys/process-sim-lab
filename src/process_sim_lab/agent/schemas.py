"""JSON schemas for every operation of the library, and a small validator for the subset they use.

Each schema describes the arguments of one tool call. It is a plain dict in the JSON Schema draft 2020-12 form, so it
can be dumped with ``json.dumps`` and handed to an agent as a tool definition. Every property states its SI unit in
its description, and every schema carries one example input under "examples".

The validator covers only the keywords these schemas use:

    type                  "object", "array", "string", "number", "integer", "boolean", "null"
    object                required, properties, additionalProperties (false or a schema for the extra values)
    number, integer       minimum, maximum, exclusiveMinimum; NaN and infinity are rejected
    string                minLength, enum
    array                 items, minItems
    annotations           $schema, title, description, examples (not checked)

Booleans are not numbers here (``True`` is not ``1``), and an integer must be a Python ``int``. A schema with any
other keyword is rejected by ``check_schema``, so a misspelt keyword cannot be ignored without notice.

Each problem is reported as a ``SchemaIssue`` with a path to the field, for example ``$.feed.flows.A`` or
``$.units[1].params.volume``; a name that is not a plain identifier is quoted: ``$.feeds["reactor-in"]``.

A flowsheet's unit "params" depend on the unit type, which this keyword subset cannot express. ``validate_arguments``
therefore checks each unit's params against ``UNIT_PARAMS_SCHEMAS`` for its type after the flowsheet schema itself.

Source: JSON Schema draft 2020-12, "JSON Schema Validation" (https://json-schema.org/draft/2020-12, accessed
2026-11-18), sections 6.1 to 6.5 for the keywords above.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from process_sim_lab.antoine import ANTOINE
from process_sim_lab.flowsheet import METHODS, UNIT_TYPES

DRAFT = "https://json-schema.org/draft/2020-12/schema"

_VALIDATION_KEYWORDS = frozenset(
    {
        "type",
        "required",
        "properties",
        "additionalProperties",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "enum",
        "items",
        "minItems",
        "minLength",
    }
)
_ANNOTATION_KEYWORDS = frozenset({"$schema", "title", "description", "examples"})
_TYPES = ("object", "array", "string", "number", "integer", "boolean", "null")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


# ---------------------------------------------------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SchemaIssue:
    """One reason an input does not match its schema.

    Attributes:
        path: where the problem is, from ``$`` (the whole input), for example ``$.volume``.
        message: what is wrong there.
    """

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "message": self.message}


def _child(path: str, key: str) -> str:
    return f"{path}.{key}" if _IDENTIFIER.fullmatch(key) else f'{path}["{key}"]'


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


def _has_type(value: Any, expected: str) -> bool:
    actual = _type_name(value)
    return actual == expected or (expected == "number" and actual == "integer")


def validate(instance: Any, schema: Mapping[str, Any], path: str = "$") -> list[SchemaIssue]:
    """Check ``instance`` against ``schema`` (the keyword subset in the module docstring).

    Returns:
        Every issue found, in document order; an empty list when the instance is valid. A value of the wrong type
        gives one issue and its contents are not checked further.
    """
    expected = schema.get("type")
    if expected is not None:
        allowed = [expected] if isinstance(expected, str) else list(expected)
        if not any(_has_type(instance, t) for t in allowed):
            return [SchemaIssue(path, f"must be of type {' or '.join(allowed)}, got {_type_name(instance)}")]

    issues: list[SchemaIssue] = []
    if "enum" in schema and instance not in schema["enum"]:
        issues.append(SchemaIssue(path, f"must be one of {schema['enum']}, got {instance!r}"))

    if _type_name(instance) in ("integer", "number"):
        if not math.isfinite(instance):
            return [SchemaIssue(path, f"must be a finite number, got {instance!r}")]
        if "minimum" in schema and instance < schema["minimum"]:
            issues.append(SchemaIssue(path, f"must be >= {schema['minimum']}, got {instance!r}"))
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            issues.append(SchemaIssue(path, f"must be > {schema['exclusiveMinimum']}, got {instance!r}"))
        if "maximum" in schema and instance > schema["maximum"]:
            issues.append(SchemaIssue(path, f"must be <= {schema['maximum']}, got {instance!r}"))

    if isinstance(instance, str) and "minLength" in schema and len(instance) < schema["minLength"]:
        issues.append(SchemaIssue(path, f"must have at least {schema['minLength']} character(s)"))

    if isinstance(instance, Mapping):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                issues.append(SchemaIssue(_child(path, key), "required field is missing"))
        extra = schema.get("additionalProperties", True)
        for key, value in instance.items():
            where = _child(path, str(key))
            if key in properties:
                issues.extend(validate(value, properties[key], where))
            elif extra is False:
                issues.append(SchemaIssue(where, f"unknown field; allowed: {', '.join(sorted(properties))}"))
            elif isinstance(extra, Mapping):
                issues.extend(validate(value, extra, where))

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            issues.append(SchemaIssue(path, f"must have at least {schema['minItems']} item(s), got {len(instance)}"))
        if "items" in schema:
            for i, value in enumerate(instance):
                issues.extend(validate(value, schema["items"], f"{path}[{i}]"))

    return issues


def check_schema(schema: Any, path: str = "#") -> None:
    """Raise ValueError when ``schema`` uses a keyword or a form the validator does not support."""
    if not isinstance(schema, Mapping):
        raise ValueError(f"{path}: a schema must be an object")
    unknown = schema.keys() - _VALIDATION_KEYWORDS - _ANNOTATION_KEYWORDS
    if unknown:
        raise ValueError(f"{path}: unsupported keywords {sorted(unknown)}")
    kind = schema.get("type")
    if kind is not None:
        kinds = [kind] if isinstance(kind, str) else kind
        if not isinstance(kinds, list) or not kinds or any(k not in _TYPES for k in kinds):
            raise ValueError(f"{path}: bad type {kind!r}")
    for name, sub in schema.get("properties", {}).items():
        check_schema(sub, f"{path}/properties/{name}")
    required = schema.get("required", [])
    if not isinstance(required, list) or any(k not in schema.get("properties", {}) for k in required):
        raise ValueError(f"{path}: every required field must be listed in properties")
    extra = schema.get("additionalProperties", True)
    if isinstance(extra, Mapping):
        check_schema(extra, f"{path}/additionalProperties")
    elif not isinstance(extra, bool):
        raise ValueError(f"{path}: additionalProperties must be a boolean or a schema")
    if "items" in schema:
        check_schema(schema["items"], f"{path}/items")
    for key in ("minimum", "maximum", "exclusiveMinimum", "minItems", "minLength"):
        if key in schema and _type_name(schema[key]) not in ("integer", "number"):
            raise ValueError(f"{path}: {key} must be a number")
    if "enum" in schema and (not isinstance(schema["enum"], list) or not schema["enum"]):
        raise ValueError(f"{path}: enum must be a non-empty list")


# ---------------------------------------------------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------------------------------------------------


def _number(description: str, **bounds: float) -> dict[str, Any]:
    return {"type": "number", "description": description, **bounds}


def _object(description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "description": description,
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _stream(description: str) -> dict[str, Any]:
    return _object(
        description,
        {
            "flows": {
                "type": "object",
                "description": "molar flow of each component, mol/s, keyed by component name",
                "additionalProperties": _number("molar flow of one component, mol/s, >= 0", minimum=0),
            },
            "temperature": _number("temperature, K, > 0; 298.15 K when left out", exclusiveMinimum=0),
            "pressure": _number("pressure, Pa, > 0; 101325 Pa when left out", exclusiveMinimum=0),
        },
        ["flows"],
    )


def _component(description: str) -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "description": description}


def _names(description: str) -> dict[str, Any]:
    return {"type": "array", "description": description, "items": {"type": "string", "minLength": 1,
                                                                    "description": "stream name"}}


def _reactor_params() -> dict[str, Any]:
    return {
        "reactant": _component("component name of the reactant A; the feed must contain it"),
        "product": _component("component name of the product B; must differ from the reactant"),
        "rate_constant": _number("first-order rate constant k, 1/s, >= 0", minimum=0),
        "volume": _number("reactor liquid volume V, m3, > 0", exclusiveMinimum=0),
        "volumetric_flow": _number("volumetric flow Q, m3/s, > 0 (constant density)", exclusiveMinimum=0),
    }


_REACTOR_REQUIRED = ["reactant", "product", "rate_constant", "volume", "volumetric_flow"]


def _flash_params() -> dict[str, Any]:
    return {
        "k_values": {
            "type": "object",
            "description": "K_i = y_i / x_i at drum conditions, dimensionless, keyed by component name; one for "
            "every component with a positive flow",
            "additionalProperties": _number("K-value of one component, dimensionless, > 0", exclusiveMinimum=0),
        },
        "tol": _number("bisection tolerance on the vapour fraction psi, dimensionless, > 0; default 1e-12",
                       exclusiveMinimum=0),
        "max_iter": {"type": "integer", "minimum": 1, "description": "most bisection steps, count, >= 1; default 200"},
    }


def _fractions() -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": 1,
        "description": "split fraction of each outlet, dimensionless, each in [0, 1], summing to 1 within 1e-9",
        "items": _number("split fraction of one outlet, dimensionless", minimum=0, maximum=1),
    }


def _mixer_temperature() -> dict[str, Any]:
    return _number("outlet temperature, K, > 0; needed only when the inlet temperatures differ", exclusiveMinimum=0)


def _tool(title: str, description: str, properties: dict[str, Any], required: list[str],
          example: dict[str, Any]) -> dict[str, Any]:
    schema = _object(description, properties, required)
    return {"$schema": DRAFT, "title": title, **schema, "examples": [example]}


# ---------------------------------------------------------------------------------------------------------------------
# Unit params inside a flowsheet (keyed like flowsheet.UNIT_TYPES)
# ---------------------------------------------------------------------------------------------------------------------

UNIT_PARAMS_SCHEMAS: dict[str, dict[str, Any]] = {
    "mixer": _object("params of a mixer unit", {"temperature": _mixer_temperature()}, []),
    "splitter": _object("params of a splitter unit", {"fractions": _fractions()}, ["fractions"]),
    "cstr": _object("params of an isothermal first-order CSTR", _reactor_params(), list(_REACTOR_REQUIRED)),
    "pfr": _object("params of an isothermal first-order PFR", _reactor_params(), list(_REACTOR_REQUIRED)),
    "flash": _object("params of an isothermal flash drum", _flash_params(), ["k_values"]),
}


# ---------------------------------------------------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------------------------------------------------

# The feed used by the CSTR and PFR unit tests: 10 mol/s A in 50 mol/s W at 330 K and 2 bar.
_REACTOR_FEED = {"flows": {"A": 10.0, "W": 50.0}, "temperature": 330.0, "pressure": 200000.0}

# examples/reactor_flash_recycle.json, kept equal to that file by tests/test_schemas.py.
_FLOWSHEET_EXAMPLE = {
    "name": "reactor-flash-recycle",
    "feeds": {"feed": {"flows": {"A": 5.6, "I": 2.4}, "temperature": 330.0, "pressure": 200000.0}},
    "units": [
        {"name": "mixer", "type": "mixer", "inlets": ["feed", "recycle"], "outlets": ["reactor-in"]},
        {
            "name": "reactor",
            "type": "cstr",
            "inlets": ["reactor-in"],
            "outlets": ["reactor-out"],
            "params": {"reactant": "A", "product": "B", "rate_constant": 0.023, "volume": 2.0, "volumetric_flow": 0.02},
        },
        {
            "name": "drum",
            "type": "flash",
            "inlets": ["reactor-out"],
            "outlets": ["vapour", "liquid"],
            "params": {"k_values": {"A": 5.0, "I": 1.0, "B": 0.3333333333333333}},
        },
        {
            "name": "purge-split",
            "type": "splitter",
            "inlets": ["vapour"],
            "outlets": ["purge", "recycle"],
            "params": {"fractions": [0.2, 0.8]},
        },
    ],
    "tear": {"streams": ["recycle"], "method": "wegstein", "tol": 1e-10, "max_iter": 100},
}


def _reactor_tool(title: str, model: str) -> dict[str, Any]:
    return _tool(
        title,
        f"{model} for one first-order, irreversible, liquid-phase reaction A -> B (rate k * C_A, constant density). "
        "Returns the outlet stream, the conversion X, the space time tau = V / Q in s and the Damkohler number.",
        {"feed": _stream("inlet stream; must contain the reactant"), **_reactor_params()},
        ["feed", *_REACTOR_REQUIRED],
        {"feed": _REACTOR_FEED, "reactant": "A", "product": "B", "rate_constant": 0.01, "volume": 2.0,
         "volumetric_flow": 0.004},
    )


TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "cstr": _reactor_tool("Isothermal CSTR", "Isothermal continuous stirred-tank reactor"),
    "pfr": _reactor_tool("Isothermal PFR", "Isothermal plug-flow reactor"),
    "mixer": _tool(
        "Mixer",
        "Mix inlet streams into one outlet: component flows add up, the outlet takes the lowest inlet pressure and "
        "the common inlet temperature (or the stated one). No reaction, no energy balance.",
        {
            "inlets": {"type": "array", "minItems": 1, "description": "inlet streams, one or more",
                       "items": _stream("one inlet stream")},
            "temperature": _mixer_temperature(),
        },
        ["inlets"],
        {
            "inlets": [
                {"flows": {"A": 2.0, "B": 1.0}, "temperature": 300.0, "pressure": 300000.0},
                {"flows": {"A": 3.0, "C": 4.0}, "temperature": 300.0, "pressure": 200000.0},
            ]
        },
    ),
    "splitter": _tool(
        "Splitter",
        "Split one stream into outlets of the same composition, temperature and pressure, by split fraction.",
        {"feed": _stream("inlet stream"), "fractions": _fractions()},
        ["feed", "fractions"],
        {"feed": {"flows": {"A": 6.0, "B": 4.0}, "temperature": 320.0, "pressure": 180000.0},
         "fractions": [0.25, 0.75]},
    ),
    "flash_drum": _tool(
        "Isothermal flash drum",
        "Flash a feed at its own temperature and pressure with given K-values (Rachford-Rice). Returns the vapour "
        "and liquid outlets, the vapour fraction psi = V / F, the phase compositions x and y and the phase label.",
        {"feed": _stream("inlet stream, total flow > 0"), **_flash_params()},
        ["feed", "k_values"],
        {"feed": {"flows": {"A": 2.0, "B": 3.0, "C": 5.0}, "temperature": 320.0, "pressure": 300000.0},
         "k_values": {"A": 5.0, "B": 1.0, "C": 0.3333333333333333}},
    ),
    "heat_exchanger_area": _tool(
        "Counter-current heat exchanger area (LMTD)",
        "Area of a counter-current heat exchanger from its duty and terminal temperatures, A = Q / (U * LMTD), with "
        "LMTD = (dT1 - dT2) / ln(dT1 / dT2), dT1 = hot_in - cold_out and dT2 = hot_out - cold_in.",
        {
            "duty": _number("heat duty Q, W, > 0", exclusiveMinimum=0),
            "overall_u": _number("overall heat-transfer coefficient U, W/(m2 K), > 0", exclusiveMinimum=0),
            "hot_in": _number("hot-side inlet temperature, K, > 0", exclusiveMinimum=0),
            "hot_out": _number("hot-side outlet temperature, K, > 0, <= hot_in", exclusiveMinimum=0),
            "cold_in": _number("cold-side inlet temperature, K, > 0", exclusiveMinimum=0),
            "cold_out": _number("cold-side outlet temperature, K, > 0, >= cold_in", exclusiveMinimum=0),
        },
        ["duty", "overall_u", "hot_in", "hot_out", "cold_in", "cold_out"],
        {"duty": 500000.0, "overall_u": 500.0, "hot_in": 423.15, "hot_out": 363.15, "cold_in": 303.15,
         "cold_out": 343.15},
    ),
    "antoine_vapour_pressure": _tool(
        "Antoine vapour pressure",
        "Vapour pressure of a pure component from the Antoine equation with NIST constants, inside the fitted "
        "temperature range.",
        {
            "component": {"type": "string", "enum": sorted(ANTOINE), "description": "pure component name"},
            "temperature": _number("temperature, K, > 0, inside the fitted range of the component",
                                   exclusiveMinimum=0),
        },
        ["component", "temperature"],
        {"component": "benzene", "temperature": 300.0},
    ),
    "antoine_saturation_temperature": _tool(
        "Antoine saturation temperature",
        "Boiling temperature of a pure component at a given pressure from the Antoine equation with NIST constants; "
        "the answer must fall inside the fitted temperature range.",
        {
            "component": {"type": "string", "enum": sorted(ANTOINE), "description": "pure component name"},
            "pressure": _number("pressure, Pa, > 0", exclusiveMinimum=0),
        },
        ["component", "pressure"],
        {"component": "benzene", "pressure": 101325.0},
    ),
    "solve_flowsheet": _tool(
        "Solve a flowsheet",
        "Solve a sequential-modular flowsheet given in the JSON form of process_sim_lab.flowsheet: feeds, units "
        "joined by named streams, and tear streams for recycle loops. Each unit's params are checked against the "
        "params schema of its type. Returns every stream, the per-unit generation and the convergence record.",
        {
            "name": {"type": "string", "description": "flowsheet name"},
            "feeds": {"type": "object", "description": "feed streams by name",
                      "additionalProperties": _stream("one feed stream")},
            "units": {
                "type": "array",
                "minItems": 1,
                "description": "unit operations; their order does not matter",
                "items": _object(
                    "one unit operation",
                    {
                        "name": {"type": "string", "minLength": 1, "description": "unique unit name"},
                        "type": {"type": "string", "enum": sorted(UNIT_TYPES), "description": "unit type"},
                        "inlets": _names("inlet stream names, in order"),
                        "outlets": _names("outlet stream names, in order (flash: vapour then liquid; splitter: one "
                                          "per fraction)"),
                        "params": {"type": "object", "description": "unit model arguments, SI units; see the params "
                                   "schema of the unit type"},
                    },
                    ["name", "type", "inlets", "outlets"],
                ),
            },
            "tear": _object(
                "tear streams and recycle solver settings",
                {
                    "streams": _names("names of the tear streams"),
                    "initial": {"type": "object", "description": "first guess of each tear stream, by name",
                                "additionalProperties": _stream("first guess of one tear stream")},
                    "method": {"type": "string", "enum": list(METHODS), "description": "update rule"},
                    "tol": _number("tolerance on the scaled residual, dimensionless, > 0; default 1e-10",
                                   exclusiveMinimum=0),
                    "max_iter": {"type": "integer", "minimum": 1, "description": "most passes, count, >= 1"},
                    "q_min": _number("lower bound on the Wegstein q, dimensionless; default -5"),
                    "q_max": _number("upper bound on the Wegstein q, dimensionless, < 1; default 0"),
                },
                [],
            ),
        },
        ["feeds", "units"],
        _FLOWSHEET_EXAMPLE,
    ),
}


def tool_definitions() -> list[dict[str, Any]]:
    """Every tool as ``{"name", "description", "input_schema"}``, the shape tool-calling APIs take."""
    return [{"name": name, "description": s["description"], "input_schema": s} for name, s in TOOL_SCHEMAS.items()]


def validate_arguments(tool: str, arguments: Any) -> list[SchemaIssue]:
    """Check the arguments of one tool call against its schema.

    For ``solve_flowsheet`` each unit's params are also checked against ``UNIT_PARAMS_SCHEMAS`` of its type.

    Raises:
        KeyError: ``tool`` is not a known tool name.
    """
    if tool not in TOOL_SCHEMAS:
        raise KeyError(f"unknown tool {tool!r}; known tools: {', '.join(TOOL_SCHEMAS)}")
    issues = validate(arguments, TOOL_SCHEMAS[tool])
    if tool == "solve_flowsheet" and not issues:
        for i, unit in enumerate(arguments["units"]):
            params_schema = UNIT_PARAMS_SCHEMAS[unit["type"]]
            issues.extend(validate(unit.get("params", {}), params_schema, f"$.units[{i}].params"))
    return issues
