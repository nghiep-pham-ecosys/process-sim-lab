"""Tests for the tool schemas and the validator.

The example inputs are the hand-checked cases of the unit tests (test_cstr, test_mixer, test_splitter, test_flash,
test_heat_exchanger, test_antoine) and the week-3 example flowsheet.
"""

import json
import math
import unittest
from pathlib import Path

from process_sim_lab.agent.schemas import (
    TOOL_SCHEMAS,
    UNIT_PARAMS_SCHEMAS,
    SchemaIssue,
    check_schema,
    tool_definitions,
    validate,
    validate_arguments,
)
from process_sim_lab.flowsheet import UNIT_TYPES

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "reactor_flash_recycle.json"

OPERATIONS = {
    "cstr",
    "pfr",
    "mixer",
    "splitter",
    "flash_drum",
    "heat_exchanger_area",
    "antoine_vapour_pressure",
    "antoine_saturation_temperature",
    "solve_flowsheet",
}


def example(tool):
    return json.loads(json.dumps(TOOL_SCHEMAS[tool]["examples"][0]))  # a deep copy through JSON


def paths(issues):
    return [i.path for i in issues]


def leaf_properties(schema, where="#"):
    """Yield (path, property schema) for every property at any depth."""
    for name, sub in schema.get("properties", {}).items():
        yield f"{where}/{name}", sub
        yield from leaf_properties(sub, f"{where}/{name}")
    extra = schema.get("additionalProperties")
    if isinstance(extra, dict):
        yield f"{where}/*", extra
        yield from leaf_properties(extra, f"{where}/*")
    if "items" in schema:
        yield f"{where}[]", schema["items"]
        yield from leaf_properties(schema["items"], f"{where}[]")


class SchemaShapeTest(unittest.TestCase):
    def test_one_schema_per_operation(self):
        self.assertEqual(set(TOOL_SCHEMAS), OPERATIONS)

    def test_every_schema_is_json_and_uses_only_supported_keywords(self):
        for name, schema in TOOL_SCHEMAS.items():
            with self.subTest(tool=name):
                self.assertEqual(json.loads(json.dumps(schema)), schema)
                check_schema(schema)
                self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertEqual(schema["type"], "object")
                self.assertFalse(schema["additionalProperties"])
                self.assertTrue(schema["title"])
                self.assertTrue(schema["description"])
        for name, schema in UNIT_PARAMS_SCHEMAS.items():
            with self.subTest(unit_type=name):
                check_schema(schema)

    def test_every_property_has_a_description(self):
        for name, schema in TOOL_SCHEMAS.items():
            for where, sub in leaf_properties(schema):
                with self.subTest(tool=name, property=where):
                    self.assertTrue(sub.get("description"))

    def test_every_number_states_a_unit(self):
        units = ("mol/s", " K", "Pa", "m3", "1/s", " W", "dimensionless", "count")
        for name, schema in TOOL_SCHEMAS.items():
            for where, sub in leaf_properties(schema):
                if sub.get("type") in ("number", "integer"):
                    with self.subTest(tool=name, property=where):
                        self.assertTrue(any(u in sub["description"] for u in units), sub["description"])

    def test_tool_definitions(self):
        defs = tool_definitions()
        self.assertEqual([d["name"] for d in defs], list(TOOL_SCHEMAS))
        for d in defs:
            self.assertEqual(set(d), {"name", "description", "input_schema"})
            self.assertIs(d["input_schema"], TOOL_SCHEMAS[d["name"]])

    def test_unit_params_match_the_flowsheet_unit_types(self):
        self.assertEqual(set(UNIT_PARAMS_SCHEMAS), set(UNIT_TYPES))
        for name, kind in UNIT_TYPES.items():
            with self.subTest(unit_type=name):
                schema = UNIT_PARAMS_SCHEMAS[name]
                self.assertEqual(set(schema["required"]), set(kind.required))
                self.assertEqual(set(schema["properties"]), set(kind.required | kind.optional))

    def test_flowsheet_example_is_the_week_3_example_file(self):
        self.assertEqual(TOOL_SCHEMAS["solve_flowsheet"]["examples"][0], json.loads(EXAMPLE.read_text("utf-8")))


class ExampleInputTest(unittest.TestCase):
    def test_every_example_validates(self):
        for name, schema in TOOL_SCHEMAS.items():
            with self.subTest(tool=name):
                self.assertEqual(len(schema["examples"]), 1)
                self.assertEqual(validate_arguments(name, example(name)), [])


class BadInputTest(unittest.TestCase):
    def test_missing_field_is_named(self):
        for name, schema in TOOL_SCHEMAS.items():
            for field in schema["required"]:
                with self.subTest(tool=name, field=field):
                    args = example(name)
                    del args[field]
                    issues = validate_arguments(name, args)
                    self.assertEqual(paths(issues), [f"$.{field}"])
                    self.assertIn("required field is missing", str(issues[0]))

    def test_wrong_type_is_named(self):
        args = example("cstr")
        args["volume"] = "2.0"
        issues = validate_arguments("cstr", args)
        self.assertEqual(paths(issues), ["$.volume"])
        self.assertIn("must be of type number, got string", issues[0].message)

    def test_negative_volume_is_named(self):
        for tool in ("cstr", "pfr"):
            with self.subTest(tool=tool):
                args = example(tool)
                args["volume"] = -1.0
                issues = validate_arguments(tool, args)
                self.assertEqual([str(i) for i in issues], ["$.volume: must be > 0, got -1.0"])

    def test_zero_volume_is_rejected(self):
        args = example("cstr")
        args["volume"] = 0
        self.assertEqual(paths(validate_arguments("cstr", args)), ["$.volume"])

    def test_boolean_is_not_a_number(self):
        args = example("cstr")
        args["rate_constant"] = True
        self.assertEqual(paths(validate_arguments("cstr", args)), ["$.rate_constant"])

    def test_non_finite_number_is_rejected(self):
        for bad in (math.nan, math.inf):
            with self.subTest(value=bad):
                args = example("heat_exchanger_area")
                args["duty"] = bad
                issues = validate_arguments("heat_exchanger_area", args)
                self.assertEqual(paths(issues), ["$.duty"])
                self.assertIn("finite", issues[0].message)

    def test_unknown_field_is_named(self):
        args = example("cstr")
        args["volum"] = 2.0
        issues = validate_arguments("cstr", args)
        self.assertEqual(paths(issues), ["$.volum"])
        self.assertIn("unknown field", issues[0].message)

    def test_nested_paths(self):
        args = example("cstr")
        args["feed"]["flows"]["A"] = -10.0
        args["feed"]["temperature"] = 0.0
        self.assertEqual(paths(validate_arguments("cstr", args)), ["$.feed.flows.A", "$.feed.temperature"])

        mixer = example("mixer")
        mixer["inlets"][1]["pressure"] = "high"
        self.assertEqual(paths(validate_arguments("mixer", mixer)), ["$.inlets[1].pressure"])

        split = example("splitter")
        split["fractions"] = [1.5, -0.5]
        self.assertEqual(paths(validate_arguments("splitter", split)), ["$.fractions[0]", "$.fractions[1]"])

    def test_empty_lists_are_rejected(self):
        self.assertEqual(paths(validate_arguments("mixer", {"inlets": []})), ["$.inlets"])
        split = example("splitter")
        split["fractions"] = []
        self.assertEqual(paths(validate_arguments("splitter", split)), ["$.fractions"])

    def test_enum(self):
        issues = validate_arguments("antoine_vapour_pressure", {"component": "unobtainium", "temperature": 300.0})
        self.assertEqual(paths(issues), ["$.component"])
        self.assertIn("benzene", issues[0].message)

    def test_integer(self):
        args = example("flash_drum")
        args["max_iter"] = 2.5
        self.assertEqual(paths(validate_arguments("flash_drum", args)), ["$.max_iter"])
        args["max_iter"] = 0
        self.assertEqual(paths(validate_arguments("flash_drum", args)), ["$.max_iter"])
        args["max_iter"] = 50
        self.assertEqual(validate_arguments("flash_drum", args), [])

    def test_flash_k_values(self):
        args = example("flash_drum")
        args["k_values"]["B"] = 0.0
        self.assertEqual(paths(validate_arguments("flash_drum", args)), ["$.k_values.B"])

    def test_not_an_object(self):
        self.assertEqual(
            [str(i) for i in validate_arguments("cstr", [1, 2])], ["$: must be of type object, got array"]
        )

    def test_flowsheet_unit_params_are_checked_by_type(self):
        args = example("solve_flowsheet")
        args["units"][1]["params"]["volume"] = -2.0
        self.assertEqual([str(i) for i in validate_arguments("solve_flowsheet", args)],
                         ["$.units[1].params.volume: must be > 0, got -2.0"])

        args = example("solve_flowsheet")
        del args["units"][2]["params"]["k_values"]
        self.assertEqual(paths(validate_arguments("solve_flowsheet", args)), ["$.units[2].params.k_values"])

        args = example("solve_flowsheet")
        args["units"][0]["type"] = "reboiler"
        self.assertEqual(paths(validate_arguments("solve_flowsheet", args)), ["$.units[0].type"])

    def test_flowsheet_stream_names_with_dashes_are_quoted(self):
        args = example("solve_flowsheet")
        args["feeds"]["fresh-feed"] = {"flows": {"A": "lots"}}
        self.assertEqual(paths(validate_arguments("solve_flowsheet", args)), ['$.feeds["fresh-feed"].flows.A'])

    def test_unknown_tool(self):
        with self.assertRaises(KeyError) as ctx:
            validate_arguments("distillation_column", {})
        self.assertIn("distillation_column", str(ctx.exception))


class ValidatorTest(unittest.TestCase):
    def test_schema_issue_text(self):
        issue = SchemaIssue("$.volume", "must be > 0, got -1")
        self.assertEqual(str(issue), "$.volume: must be > 0, got -1")
        self.assertEqual(issue.to_dict(), {"path": "$.volume", "message": "must be > 0, got -1"})

    def test_integer_is_a_number(self):
        self.assertEqual(validate(2, {"type": "number", "minimum": 0}), [])

    def test_type_list(self):
        schema = {"type": ["number", "null"]}
        self.assertEqual(validate(None, schema), [])
        self.assertEqual(paths(validate("x", schema)), ["$"])

    def test_maximum_and_min_length(self):
        self.assertEqual(paths(validate(1.5, {"type": "number", "maximum": 1})), ["$"])
        self.assertEqual(paths(validate("", {"type": "string", "minLength": 1})), ["$"])

    def test_check_schema_rejects_unsupported_forms(self):
        bad = [
            {"type": "object", "oneOf": []},
            {"type": "decimal"},
            {"type": "object", "properties": {"a": {"type": "number"}}, "required": ["b"]},
            {"type": "object", "additionalProperties": "no"},
            {"type": "number", "minimum": "0"},
            {"enum": []},
            {"type": "array", "items": {"pattern": "x"}},
        ]
        for schema in bad:
            with self.subTest(schema=schema), self.assertRaises(ValueError):
                check_schema(schema)


if __name__ == "__main__":
    unittest.main()
