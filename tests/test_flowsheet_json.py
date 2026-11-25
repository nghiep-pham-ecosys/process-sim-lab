"""Tests for the JSON output of a solved flowsheet: RESULT_SCHEMA, check_result and the command line.

The reactor-flash-recycle example has an exact converged state (derived in tests/test_flowsheet.py): recycle
(1, 3/5, 2/5), purge (1/4, 3/20, 1/10) and liquid (3/4, 9/4, 9/2) mol/s for (A, I, B), and a reaction extent of
23/5 mol/s in the CSTR. The committed result file must hold that answer within VALUE_TOL and validate.
"""

import contextlib
import io
import json
import math
import tempfile
import unittest
from pathlib import Path

from process_sim_lab.agent.runner import run_tool
from process_sim_lab.agent.schemas import check_schema
from process_sim_lab.flowsheet import solve_flowsheet
from process_sim_lab.flowsheet_json import RESULT_SCHEMA, check_result, dumps, main

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "reactor_flash_recycle.json"
EXAMPLE_RESULT = ROOT / "examples" / "reactor_flash_recycle.result.json"
VALUE_TOL = 1e-8  # converged values against the exact answer (tear tol 1e-10), as in tests/test_flowsheet.py
BALANCE_TOL = 1e-6
SAME_TOL = 1e-9  # committed file against a fresh solve; allows last-digit differences between platforms

EXACT = {
    "recycle": {"A": 1.0, "I": 0.6, "B": 0.4},
    "purge": {"A": 0.25, "I": 0.15, "B": 0.1},
    "liquid": {"A": 0.75, "I": 2.25, "B": 4.5},
    "reactor-out": {"A": 2.0, "I": 3.0, "B": 5.0},
}

NO_RECYCLE = {
    "name": "reactor-then-flash",
    "feeds": {"feed": {"flows": {"A": 10.0, "W": 50.0}, "temperature": 330.0, "pressure": 200000.0}},
    "units": [
        {"name": "reactor", "type": "pfr", "inlets": ["feed"], "outlets": ["out"],
         "params": {"reactant": "A", "product": "B", "rate_constant": 0.01, "volume": 2.0, "volumetric_flow": 0.004}},
    ],
}


# A cooler feeding a shortcut column: the exchanger and column sizing fields in one result (no recycle).
COOLER_COLUMN = {
    "name": "cooler-then-column",
    "feeds": {"feed": {"flows": {"benzene": 40.0, "toluene": 30.0, "cumene": 30.0}, "temperature": 420.0,
                       "pressure": 101325.0}},
    "units": [
        {"name": "cooler", "type": "heat_exchanger", "inlets": ["feed"], "outlets": ["column-in"],
         "params": {"temperature": 380.0, "heat_capacities": {"benzene": 140.0, "toluene": 160.0, "cumene": 220.0},
                    "overall_u": 400.0, "utility_in": 300.0, "utility_out": 330.0}},
        {"name": "column", "type": "shortcut_column", "inlets": ["column-in"], "outlets": ["distillate", "bottoms"],
         "params": {"relative_volatilities": {"benzene": 2.25, "toluene": 1.0, "cumene": 0.21},
                    "light_key": "toluene", "heavy_key": "cumene", "light_key_recovery": 0.95,
                    "heavy_key_recovery": 0.98, "q": 0.0, "reflux_ratio": 2.0}},
    ],
}


def example_spec():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def example_result():
    return json.loads(dumps(solve_flowsheet(example_spec()).to_dict()))


def messages(issues):
    return [str(i) for i in issues]


def run_main(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


def walk(schema, path="#"):
    yield path, schema
    for name, sub in schema.get("properties", {}).items():
        yield from walk(sub, f"{path}/properties/{name}")
    for key in ("additionalProperties", "items"):
        if isinstance(schema.get(key), dict):
            yield from walk(schema[key], f"{path}/{key}")


def assert_numbers_close(test, a, b, tol, path="$"):
    if isinstance(a, dict):
        test.assertEqual(list(a), list(b), path)
        for k in a:
            assert_numbers_close(test, a[k], b[k], tol, f"{path}.{k}")
    elif isinstance(a, list):
        test.assertEqual(len(a), len(b), path)
        for i, (x, y) in enumerate(zip(a, b)):
            assert_numbers_close(test, x, y, tol, f"{path}[{i}]")
    elif isinstance(a, float) or isinstance(b, float):
        test.assertLessEqual(abs(a - b), tol, path)
    else:
        test.assertEqual(a, b, path)


class SchemaShapeTest(unittest.TestCase):
    def test_uses_only_supported_keywords_and_is_json(self):
        check_schema(RESULT_SCHEMA)
        self.assertEqual(json.loads(json.dumps(RESULT_SCHEMA)), RESULT_SCHEMA)
        self.assertEqual(RESULT_SCHEMA["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_every_number_states_a_unit_or_is_dimensionless(self):
        units = ("mol/s", " K", "Pa", "dimensionless", "count",
                 " m,", " m2,", " m3,", " s,", " W,", " kg/m3,", " m3/s,", " m/s,")
        for path, schema in walk(RESULT_SCHEMA):
            if schema.get("type") in ("number", "integer") and "description" in schema:
                with self.subTest(path=path):
                    self.assertTrue(any(u in schema["description"] for u in units), schema["description"])
        for path, schema in walk(RESULT_SCHEMA):
            extra = schema.get("additionalProperties")
            if isinstance(extra, dict) and extra.get("type") == "number":
                with self.subTest(path=path):
                    self.assertIn("mol/s", schema["description"])

    def test_every_object_is_closed_or_typed(self):
        for path, schema in walk(RESULT_SCHEMA):
            if schema.get("type") == "object":
                with self.subTest(path=path):
                    self.assertIn("additionalProperties", schema)

    def test_requires_every_key_of_to_dict(self):
        self.assertEqual(set(RESULT_SCHEMA["required"]), set(example_result()))
        self.assertEqual(set(RESULT_SCHEMA["properties"]), set(example_result()))


class ExampleResultTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = example_result()
        cls.committed = json.loads(EXAMPLE_RESULT.read_text(encoding="utf-8"))

    def test_fresh_result_validates(self):
        self.assertEqual(messages(check_result(self.result)), [])

    def test_committed_result_validates(self):
        self.assertEqual(messages(check_result(self.committed)), [])

    def test_committed_result_matches_a_fresh_solve(self):
        assert_numbers_close(self, self.committed, self.result, SAME_TOL)

    def test_committed_result_holds_the_exact_answer(self):
        r = self.committed
        self.assertEqual(r["method"], "wegstein")
        self.assertLessEqual(r["residual"], r["tol"])
        for stream, flows in EXACT.items():
            for c, value in flows.items():
                with self.subTest(stream=stream, component=c):
                    self.assertAlmostEqual(r["streams"][stream]["flows"][c], value, delta=VALUE_TOL)
        self.assertAlmostEqual(r["units"]["reactor"]["generation"]["B"], 4.6, delta=VALUE_TOL)
        for c, residual in r["overall_balance"].items():
            with self.subTest(balance=c):
                self.assertLessEqual(abs(residual), BALANCE_TOL)

    def test_committed_file_is_the_dumps_form(self):
        self.assertEqual(EXAMPLE_RESULT.read_text(encoding="utf-8"), dumps(self.committed))

    def test_direct_substitution_result_validates(self):
        r = solve_flowsheet(example_spec(), method="direct").to_dict()
        self.assertEqual(messages(check_result(r)), [])
        self.assertGreater(r["iterations"], self.result["iterations"])

    def test_flowsheet_without_recycle_validates(self):
        r = json.loads(dumps(solve_flowsheet(NO_RECYCLE).to_dict()))
        self.assertEqual(messages(check_result(r)), [])
        self.assertEqual((r["iterations"], r["residual"], r["history"]), (1, 0.0, [0.0]))
        self.assertEqual(r["products"], ["out"])

    def test_committed_result_carries_the_sizing(self):
        units = self.committed["units"]
        self.assertEqual(units["reactor"]["sizing"], {"volume": 2.0, "space_time": 100.0})
        self.assertAlmostEqual(units["drum"]["sizing"]["diameter"], 0.2058450630, delta=1e-9)  # test_flash_drum_sizing
        self.assertAlmostEqual(units["drum"]["sizing"]["height"], 0.8233802520, delta=1e-9)
        self.assertEqual((units["mixer"]["sizing"], units["purge-split"]["sizing"]), ({}, {}))

    def test_exchanger_and_column_result_validates(self):
        r = json.loads(dumps(solve_flowsheet(COOLER_COLUMN).to_dict()))
        self.assertEqual(messages(check_result(r)), [])
        self.assertEqual(list(r["units"]["cooler"]["sizing"]), ["duty", "area", "lmtd"])
        self.assertEqual(list(r["units"]["column"]["sizing"]),
                         ["minimum_stages", "stages", "minimum_reflux", "reflux_ratio"])
        # Q = (40 * 140 + 30 * 160 + 30 * 220) * (420 - 380) = 17 000 * 40 = 680 000 W.
        self.assertAlmostEqual(r["units"]["cooler"]["sizing"]["duty"], 680000.0, places=6)

    def test_tool_result_validates(self):
        out = run_tool("solve_flowsheet", example_spec())
        self.assertTrue(out["ok"], out)
        self.assertEqual(messages(check_result(out["result"])), [])


class BadResultTest(unittest.TestCase):
    def setUp(self):
        self.r = example_result()

    def assertIssue(self, path, fragment):
        found = messages(check_result(self.r))
        self.assertTrue(any(m.startswith(f"{path}: ") and fragment in m for m in found), found)

    def test_not_an_object(self):
        self.assertEqual(messages(check_result([])), ["$: must be of type object, got array"])

    def test_missing_key(self):
        del self.r["history"]
        self.assertIssue("$.history", "required field is missing")

    def test_unknown_key(self):
        self.r["notes"] = "x"
        self.assertIssue("$.notes", "unknown field")

    def test_negative_flow(self):
        self.r["streams"]["purge"]["flows"]["A"] = -0.25
        self.assertIssue("$.streams.purge.flows.A", "must be >= 0")

    def test_zero_temperature(self):
        self.r["streams"]["feed"]["temperature"] = 0.0
        self.assertIssue("$.streams.feed.temperature", "must be > 0")

    def test_non_finite_number(self):
        self.r["overall_balance"]["A"] = math.nan
        self.assertIssue("$.overall_balance.A", "finite")

    def test_unknown_method_and_unit_type(self):
        self.r["method"] = "newton"
        self.r["units"]["drum"]["type"] = "column"
        self.assertIssue("$.method", "must be one of")
        self.assertIssue("$.units.drum.type", "must be one of")

    def test_reference_to_a_missing_stream(self):
        self.r["units"]["mixer"]["inlets"][1] = "recycel"
        self.assertIssue("$.units.mixer.inlets[1]", "'recycel'")

    def test_product_that_is_not_a_stream(self):
        self.r["products"].append("vent")
        self.assertIssue("$.products[2]", "'vent'")

    def test_quoted_names_in_paths(self):
        self.r["units"]["purge-split"]["outlets"][1] = "recycel"
        self.assertIssue('$.units["purge-split"].outlets[1]', "'recycel'")

    def test_orphan_stream(self):
        self.r["streams"]["spare"] = {"flows": {}, "temperature": 300.0, "pressure": 1e5}
        self.assertIssue("$.streams.spare", "neither a feed nor the outlet")

    def test_component_not_listed(self):
        self.r["streams"]["liquid"]["flows"]["W"] = 1.0
        self.r["units"]["reactor"]["generation"]["C"] = 0.0
        self.assertIssue("$.streams.liquid.flows", "'W'")
        self.assertIssue("$.units.reactor.generation", "'C'")

    def test_balance_needs_every_component(self):
        del self.r["overall_balance"]["I"]
        self.assertIssue("$.overall_balance", "one entry per component")

    def test_history_length(self):
        self.r["iterations"] += 1
        self.assertIssue("$.history", "entries for")

    def test_residual_is_the_last_history_entry(self):
        self.r["residual"] = 0.0
        self.assertIssue("$.residual", "last history entry")

    def test_sizing_missing_a_field(self):
        del self.r["units"]["reactor"]["sizing"]["space_time"]
        self.assertIssue("$.units.reactor.sizing", "a cstr must have the fields ['volume', 'space_time']")

    def test_sizing_field_of_another_type(self):
        self.r["units"]["mixer"]["sizing"]["area"] = 1.0
        self.assertIssue("$.units.mixer.sizing", "a mixer must have the fields []")

    def test_unknown_sizing_field(self):
        self.r["units"]["drum"]["sizing"]["weight"] = 1.0
        self.assertIssue("$.units.drum.sizing.weight", "unknown field")

    def test_flash_sizing_is_all_or_none(self):
        self.r["units"]["drum"]["sizing"] = {}
        self.assertEqual(messages(check_result(self.r)), [])
        self.r["units"]["drum"]["sizing"] = {"diameter": 0.2}
        self.assertIssue("$.units.drum.sizing", "or none")

    def test_sizing_must_be_positive(self):
        self.r["units"]["drum"]["sizing"]["diameter"] = 0.0
        self.assertIssue("$.units.drum.sizing.diameter", "must be > 0")
        for name, schema in RESULT_SCHEMA["properties"]["units"]["additionalProperties"]["properties"]["sizing"][
                "properties"].items():
            with self.subTest(field=name):
                self.assertEqual(schema.get("exclusiveMinimum"), 0)

    def test_residual_above_tol(self):
        self.r["tol"] = 1e-14
        self.assertIssue("$.residual", "above tol")


class CommandLineTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def write(self, name, data):
        path = self.tmp / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def test_solve_to_file_then_check(self):
        out = self.tmp / "result.json"
        code, stdout, stderr = run_main("solve", str(EXAMPLE), "-o", str(out))
        self.assertEqual((code, stdout), (0, ""))
        self.assertIn("3 passes", stderr)
        self.assertEqual(messages(check_result(json.loads(out.read_text("utf-8")))), [])
        code, stdout, _ = run_main("check", str(out))
        self.assertEqual(code, 0)
        self.assertIn("valid", stdout)

    def test_solve_to_stdout(self):
        code, stdout, _ = run_main("solve", str(EXAMPLE))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["name"], "reactor-flash-recycle")

    def test_check_reports_issues(self):
        bad = example_result()
        bad["tol"] = 1e-14
        code, _, stderr = run_main("check", self.write("bad.json", bad))
        self.assertEqual(code, 1)
        self.assertIn("$.residual", stderr)

    def test_invalid_spec_is_named_by_path(self):
        spec = example_spec()
        spec["units"][1]["params"]["volume"] = -2.0
        code, stdout, stderr = run_main("solve", self.write("spec.json", spec))
        self.assertEqual((code, stdout), (1, ""))
        self.assertIn("$.units[1].params.volume", stderr)

    def test_loop_that_does_not_converge(self):
        spec = example_spec()
        spec["tear"]["max_iter"] = 1
        code, _, stderr = run_main("solve", self.write("spec.json", spec))
        self.assertEqual(code, 1)
        self.assertIn("did not converge", stderr)

    def test_unit_error(self):
        spec = example_spec()
        spec["tear"]["streams"] = ["reactor-out"]  # unguessed tear upstream of the flash
        code, _, stderr = run_main("solve", self.write("spec.json", spec))
        self.assertEqual(code, 1)
        self.assertIn("cannot be solved", stderr)
        self.assertIn("'drum'", stderr)

    def test_missing_and_malformed_files(self):
        self.assertEqual(run_main("solve", str(self.tmp / "none.json"))[0], 1)
        bad = self.tmp / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        self.assertEqual(run_main("check", str(bad))[0], 1)

    def test_output_that_cannot_be_written(self):
        code, _, stderr = run_main("solve", str(EXAMPLE), "-o", str(self.tmp / "missing" / "result.json"))
        self.assertEqual(code, 1)
        self.assertIn("cannot write", stderr)

    def test_schema(self):
        code, stdout, _ = run_main("schema")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout), RESULT_SCHEMA)


if __name__ == "__main__":
    unittest.main()
