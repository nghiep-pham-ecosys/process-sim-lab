"""Run every python block of the README so the examples cannot rot.

Each block runs in its own namespace, with the repository root as the working directory (the flowsheet example
loads a file by relative path). Blocks carry their own `assert` hand-checks; a block that raises fails the test.
"""

import contextlib
import io
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLOCK = re.compile(r"^```python\n(.*?)^```", re.DOTALL | re.MULTILINE)


class ReadmeExamplesTest(unittest.TestCase):
    def test_every_python_block_runs(self):
        blocks = BLOCK.findall((ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(blocks), 8)
        previous = Path.cwd()
        os.chdir(ROOT)
        try:
            for i, code in enumerate(blocks, start=1):
                with self.subTest(block=i, first_line=code.splitlines()[0]):
                    with contextlib.redirect_stdout(io.StringIO()):
                        exec(compile(code, f"README.md block {i}", "exec"), {"__name__": "__readme__"})
        finally:
            os.chdir(previous)

    def test_every_week2_unit_has_an_example(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        for name in (
            "isothermal_pfr_first_order",
            "mix_streams",
            "split_stream",
            "isothermal_flash",
            "counter_current_area",
            "log_mean_temperature_difference",
            "vapour_pressure",
            "saturation_temperature",
        ):
            with self.subTest(name=name):
                self.assertIn(f"{name}(", text)


if __name__ == "__main__":
    unittest.main()
