"""Tests for the tool runner and the evaluation cases."""

import contextlib
import io
import json
import unittest
from pathlib import Path

from process_sim_lab.agent.evaluate import (
    DEFAULT_CASES,
    evaluate,
    load_cases,
    main,
    parse_case,
    resolve_pointer,
    run_case,
)
from process_sim_lab.agent.runner import (
    CONVERGENCE_ERROR,
    INVALID_INPUT,
    MODEL_ERROR,
    OPERATIONS,
    UNKNOWN_TOOL,
    run_tool,
)
from process_sim_lab.agent.schemas import TOOL_SCHEMAS

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "reactor_flash_recycle.json"


def example(tool):
    return json.loads(json.dumps(TOOL_SCHEMAS[tool]["examples"][0]))


def linear_loop(**tear):
    """The linear recycle loop of test_flowsheet: feed 10 mol/s A, CSTR with Da = 1, purge 1/5."""
    return {
        "feeds": {"feed": {"flows": {"A": 10.0}}},
        "units": [
            {"name": "mixer", "type": "mixer", "inlets": ["feed", "recycle"], "outlets": ["s1"]},
            {"name": "reactor", "type": "cstr", "inlets": ["s1"], "outlets": ["s2"],
             "params": {"reactant": "A", "product": "B", "rate_constant": 0.01, "volume": 2.0,
                        "volumetric_flow": 0.02}},
            {"name": "split", "type": "splitter", "inlets": ["s2"], "outlets": ["purge", "recycle"],
             "params": {"fractions": [0.2, 0.8]}},
        ],
        "tear": {"streams": ["recycle"], **tear},
    }


class RunToolTest(unittest.TestCase):
    def test_every_operation_has_a_runner(self):
        self.assertEqual(set(OPERATIONS), set(TOOL_SCHEMAS))

    def test_every_example_runs_and_is_json_safe(self):
        for name in TOOL_SCHEMAS:
            with self.subTest(tool=name):
                out = run_tool(name, example(name))
                self.assertTrue(out["ok"], out)
                self.assertEqual(out["tool"], name)
                text = json.dumps(out, allow_nan=False)
                self.assertEqual(json.loads(text), out)

    def test_cstr_result(self):
        # tests/test_cstr.py: tau = 500 s, Da = 5, X = 5/6.
        out = run_tool("cstr", example("cstr"))
        r = out["result"]
        self.assertAlmostEqual(r["conversion"], 5.0 / 6.0, places=12)
        self.assertAlmostEqual(r["space_time"], 500.0)
        self.assertAlmostEqual(r["outlet"]["flows"]["B"], 50.0 / 6.0, places=12)
        self.assertEqual(r["outlet"]["temperature"], 330.0)

    def test_arguments_as_json_text(self):
        out = run_tool("cstr", json.dumps(example("cstr")))
        self.assertTrue(out["ok"])
        self.assertAlmostEqual(out["result"]["conversion"], 5.0 / 6.0, places=12)

    def test_linear_loop(self):
        # tests/test_flowsheet.py: purge 1/5 gives R_A = 20/3 and R_B = 100/3 mol/s.
        out = run_tool("solve_flowsheet", linear_loop())
        self.assertTrue(out["ok"], out)
        recycle = out["result"]["streams"]["recycle"]["flows"]
        self.assertAlmostEqual(recycle["A"], 20.0 / 3.0, delta=1e-8)
        self.assertAlmostEqual(recycle["B"], 100.0 / 3.0, delta=1e-8)
        self.assertEqual(len(out["result"]["history"]), out["result"]["iterations"])


class StructuredErrorTest(unittest.TestCase):
    def test_unknown_tool(self):
        out = run_tool("distillation_column", {"stages": 10})
        self.assertEqual(out["ok"], False)
        self.assertEqual(out["tool"], "distillation_column")
        self.assertEqual(out["error"]["type"], UNKNOWN_TOOL)
        self.assertIn("distillation_column", out["error"]["message"])
        self.assertEqual(out["error"]["known_tools"], list(TOOL_SCHEMAS))
        json.dumps(out, allow_nan=False)

    def test_tool_name_that_is_not_a_string(self):
        out = run_tool(["cstr"], {})
        self.assertEqual(out["error"]["type"], UNKNOWN_TOOL)
        self.assertEqual(out["tool"], "['cstr']")

    def test_invalid_input_names_every_field(self):
        args = example("cstr")
        args["volume"] = -2.0
        del args["reactant"]
        out = run_tool("cstr", args)
        self.assertEqual(out["ok"], False)
        self.assertEqual(out["error"]["type"], INVALID_INPUT)
        self.assertEqual(
            out["error"]["issues"],
            [
                {"path": "$.reactant", "message": "required field is missing"},
                {"path": "$.volume", "message": "must be > 0, got -2.0"},
            ],
        )
        self.assertIn("$.volume", out["error"]["message"])

    def test_invalid_input_in_a_flowsheet_unit(self):
        args = example("solve_flowsheet")
        args["units"][1]["params"]["volume"] = -2.0
        out = run_tool("solve_flowsheet", args)
        self.assertEqual(out["error"]["type"], INVALID_INPUT)
        self.assertEqual([i["path"] for i in out["error"]["issues"]], ["$.units[1].params.volume"])

    def test_bad_json_text(self):
        out = run_tool("cstr", '{"volume": ')
        self.assertEqual(out["error"]["type"], INVALID_INPUT)
        self.assertEqual(out["error"]["issues"][0]["path"], "$")

    def test_nan_in_json_text(self):
        args = example("heat_exchanger_area")
        text = json.dumps(args).replace("500000.0", "NaN")
        out = run_tool("heat_exchanger_area", text)
        self.assertEqual(out["error"]["type"], INVALID_INPUT)
        self.assertEqual(out["error"]["issues"][0]["path"], "$.duty")
        json.dumps(out, allow_nan=False)

    def test_model_error(self):
        # Valid shape, but a temperature cross at the hot end: cold_out 430 K > hot_in 423.15 K.
        args = example("heat_exchanger_area")
        args["cold_out"] = 430.0
        out = run_tool("heat_exchanger_area", args)
        self.assertEqual(out["error"]["type"], MODEL_ERROR)
        self.assertIn("temperature cross", out["error"]["message"])

        out = run_tool("antoine_vapour_pressure", {"component": "benzene", "temperature": 360.0})
        self.assertEqual(out["error"]["type"], MODEL_ERROR)
        self.assertIn("outside the fitted range", out["error"]["message"])

        args = example("splitter")
        args["fractions"] = [0.5, 0.4]
        out = run_tool("splitter", args)
        self.assertEqual(out["error"]["type"], MODEL_ERROR)

        args = example("solve_flowsheet")
        args["units"][0]["inlets"] = ["feed", "nowhere"]
        out = run_tool("solve_flowsheet", args)
        self.assertEqual(out["error"]["type"], MODEL_ERROR)

        args = example("shortcut_column")
        args["reflux_factor"] = 1.3  # reflux_ratio is given too
        out = run_tool("shortcut_column", args)
        self.assertEqual(out["error"]["type"], MODEL_ERROR)
        self.assertIn("exactly one", out["error"]["message"])

        del args["reflux_ratio"]
        args["reflux_factor"] = 1.00001  # Gilliland needs infinitely many stages at this resolution
        out = run_tool("shortcut_column", args)
        self.assertEqual(out["error"]["type"], MODEL_ERROR)
        self.assertIn("too close to R_min", out["error"]["message"])

    def test_shortcut_column_result(self):
        # tests/test_shortcut_column.py: Wankat Examples 7-1 and 7-2, N_min = ln(931) / ln(1 / 0.21).
        r = run_tool("shortcut_column", example("shortcut_column"))["result"]
        self.assertAlmostEqual(r["minimum_stages"], 4.3804, delta=5e-5)
        self.assertAlmostEqual(r["minimum_reflux"], 0.6663, delta=0.00067)
        self.assertAlmostEqual(r["distillate"]["flows"]["toluene"], 28.5, delta=1e-9)
        self.assertGreater(r["stages"], r["minimum_stages"])

    def test_convergence_error(self):
        out = run_tool("solve_flowsheet", linear_loop(method="direct", max_iter=2))
        self.assertEqual(out["error"]["type"], CONVERGENCE_ERROR)
        self.assertEqual(out["error"]["iterations"], 2)
        self.assertGreater(out["error"]["residual"], 1e-10)
        json.dumps(out, allow_nan=False)


class EvaluationCaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = load_cases(DEFAULT_CASES)

    def test_eleven_cases_one_per_file(self):
        self.assertEqual(DEFAULT_CASES, REPO / "evals" / "cases")
        self.assertEqual(len(self.cases), 11)
        self.assertEqual(len(list(DEFAULT_CASES.glob("*.json"))), 11)

    def test_every_operation_is_covered(self):
        self.assertEqual({c.tool for c in self.cases}, set(TOOL_SCHEMAS))

    def test_every_case_names_its_source_test(self):
        for c in self.cases:
            with self.subTest(case=c.id):
                self.assertRegex(c.source, r"tests/test_\w+\.py")
                self.assertIn("Tolerance", c.source)

    def test_every_case_arguments_validate(self):
        for c in self.cases:
            with self.subTest(case=c.id):
                self.assertTrue(run_tool(c.tool, c.arguments)["ok"])

    def test_flowsheet_case_uses_the_week_3_example(self):
        (case,) = [c for c in self.cases if c.tool == "solve_flowsheet"]
        self.assertEqual(case.arguments, json.loads(EXAMPLE.read_text(encoding="utf-8")))

    def test_all_cases_pass(self):
        results = evaluate(self.cases)
        self.assertEqual([r.failures for r in results if not r.passed], [])

    def test_main_reports_eleven_of_eleven(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main([])
        self.assertEqual(code, 0)
        lines = buffer.getvalue().splitlines()
        self.assertEqual(lines[-1], "11/11 cases passed")
        self.assertEqual(sum(line.startswith("PASS") for line in lines), 11)


class EvaluateMechanicsTest(unittest.TestCase):
    def case(self, **changes):
        obj = {
            "id": "synthetic",
            "description": "a synthetic case",
            "source": "tests/test_cstr.py, Tolerance 1e-12",
            "call": {"name": "cstr", "arguments": example("cstr")},
            "expected": [{"pointer": "/conversion", "value": 5.0 / 6.0, "abs_tol": 1e-12}],
        }
        obj.update(changes)
        return parse_case(obj, "synthetic.json")

    def test_a_wrong_expectation_fails(self):
        r = run_case(self.case(expected=[{"pointer": "/conversion", "value": 0.5, "abs_tol": 1e-12},
                                         {"pointer": "/outlet/flows/Z", "value": 1.0, "abs_tol": 1.0}]))
        self.assertFalse(r.passed)
        self.assertEqual(len(r.failures), 2)
        self.assertIn("/conversion: expected 0.5", r.failures[0])
        self.assertIn("not in the result", r.failures[1])

    def test_a_failed_call_fails_the_case(self):
        r = run_case(self.case(call={"name": "cstr", "arguments": {}}))
        self.assertFalse(r.passed)
        self.assertIn("invalid_input", r.failures[0])

    def test_non_numbers_compare_equal(self):
        r = run_case(self.case(call={"name": "flash_drum", "arguments": example("flash_drum")},
                               expected=[{"pointer": "/phase", "value": "liquid"}]))
        self.assertEqual(r.failures, ("/phase: expected 'liquid', got 'two-phase'",))

    def test_a_folder_without_cases_is_rejected(self):
        with self.assertRaises(ValueError):
            load_cases(REPO / "src")

    def test_bad_case_files_are_rejected(self):
        bad = [
            {"expected": []},
            {"expected": [{"pointer": "/conversion", "value": 0.5}]},  # a number needs abs_tol
            {"expected": [{"pointer": "conversion", "value": "x"}]},
            {"call": {"name": "cstr"}},
            {"source": ""},
            {"extra": 1},
        ]
        for change in bad:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.case(**change)

    def test_resolve_pointer(self):
        doc = {"a": [{"b/c": 1, "d~e": 2}], "": 3}
        self.assertEqual(resolve_pointer(doc, "/a/0/b~1c"), 1)
        self.assertEqual(resolve_pointer(doc, "/a/0/d~0e"), 2)
        self.assertEqual(resolve_pointer(doc, "/"), 3)
        for missing in ("/a/1", "/a/x", "/z", "/a/0/b"):
            with self.subTest(pointer=missing), self.assertRaises(KeyError):
                resolve_pointer(doc, missing)


if __name__ == "__main__":
    unittest.main()
