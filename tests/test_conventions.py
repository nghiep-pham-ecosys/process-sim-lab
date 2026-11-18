"""Repository conventions (docs/spec.md section 3): every model module states a source and has a test file."""

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "process_sim_lab"
TESTS = ROOT / "tests"


def model_modules():
    """Unit modules plus antoine.py and flowsheet.py (package and helper modules excluded)."""
    paths = sorted((PACKAGE / "units").glob("*.py"))
    paths = [p for p in paths if p.name != "__init__.py"]
    return paths + [PACKAGE / "antoine.py", PACKAGE / "flowsheet.py"]


def has_source_line(path):
    docstring = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
    return any(line.startswith(("Source:", "Sources:", "Source of")) for line in docstring.splitlines())


class ConventionsTest(unittest.TestCase):
    def test_modules_found(self):
        self.assertGreaterEqual(len(model_modules()), 7)

    def test_every_model_module_states_a_source(self):
        for path in model_modules():
            with self.subTest(module=path.name):
                self.assertTrue(has_source_line(path), f"{path.name}: no 'Source:' line in the module docstring")

    def test_every_model_module_has_a_test_file(self):
        for path in model_modules():
            with self.subTest(module=path.name):
                self.assertTrue((TESTS / f"test_{path.stem}.py").is_file(), f"missing tests/test_{path.stem}.py")


if __name__ == "__main__":
    unittest.main()
