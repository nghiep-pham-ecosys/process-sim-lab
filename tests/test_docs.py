"""Tests for the docs site: one page per unit, every page in the nav, runnable examples, links that leave docs/.

These run with the standard library only. The site build itself (``mkdocs build --strict``) runs in
.github/workflows/pages.yml, and here only when the optional extra ``docs`` is installed.
"""

import contextlib
import importlib.util
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
UNITS = ROOT / "src" / "process_sim_lab" / "units"
MKDOCS_YML = ROOT / "mkdocs.yml"
BLOCK = re.compile(r"^```python\n(.*?)^```", re.DOTALL | re.MULTILINE)
# A nav entry: "- Title: path.md" or "- path.md" (mkdocs.yml is read without PyYAML, which the core does not need).
NAV_ENTRY = re.compile(r"^\s*-\s+(?:[^:\n]+:\s+)?([\w./-]+\.md)\s*$", re.MULTILINE)
# Unit modules documented on another module's page: the drum sizing is on the flash drum page.
PAGE_OF = {"flash_drum_sizing": "flash"}
REPO_URL = "https://github.com/nghiep-pham-ecosys/process-sim-lab"

spec = importlib.util.spec_from_file_location("mkdocs_hooks", ROOT / "mkdocs_hooks.py")
mkdocs_hooks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mkdocs_hooks)


def unit_modules():
    return sorted(p.stem for p in UNITS.glob("*.py") if p.name != "__init__.py")


def nav_pages():
    text = MKDOCS_YML.read_text(encoding="utf-8")
    return NAV_ENTRY.findall(text.split("\nnav:", 1)[1])


def doc_pages():
    return sorted(p.relative_to(DOCS).as_posix() for p in DOCS.rglob("*.md"))


class UnitPagesTest(unittest.TestCase):
    def test_modules_found(self):
        self.assertGreaterEqual(len(unit_modules()), 8)

    def test_every_unit_module_has_a_page_that_links_its_code(self):
        for stem in unit_modules():
            page = DOCS / "units" / f"{PAGE_OF.get(stem, stem)}.md"
            with self.subTest(module=stem):
                self.assertTrue(page.is_file(), f"missing {page.relative_to(ROOT)}")
                self.assertIn(f"](../../src/process_sim_lab/units/{stem}.py)", page.read_text(encoding="utf-8"))

    def test_every_unit_page_is_in_the_nav(self):
        nav = nav_pages()
        for stem in unit_modules():
            with self.subTest(module=stem):
                self.assertIn(f"units/{PAGE_OF.get(stem, stem)}.md", nav)

    def test_every_unit_page_states_a_source(self):
        for page in sorted((DOCS / "units").glob("*.md")):
            with self.subTest(page=page.name):
                self.assertRegex(page.read_text(encoding="utf-8"), r"(?m)^## Sources?$")


class NavTest(unittest.TestCase):
    def test_nav_lists_every_page_once(self):
        nav = nav_pages()
        self.assertEqual(sorted(nav), doc_pages())
        self.assertEqual(len(nav), len(set(nav)))

    def test_existing_docs_are_in_the_nav(self):
        for page in ("index.md", "spec.md", "flowsheet-worked-example.md", "antoine.md", "flowsheet.md", "agent.md",
                     "demo.md"):
            with self.subTest(page=page):
                self.assertIn(page, nav_pages())

    def test_site_settings(self):
        text = MKDOCS_YML.read_text(encoding="utf-8")
        self.assertIn("strict: true", text)
        self.assertIn(f"repo_url: {REPO_URL}\n", text)
        self.assertIn("  - mkdocs_hooks.py\n", text)


class DocExamplesTest(unittest.TestCase):
    """Run every python block of every page, so the site examples cannot rot (as tests/test_readme.py)."""

    def test_every_python_block_runs(self):
        previous = Path.cwd()
        os.chdir(ROOT)
        count = 0
        try:
            for page in doc_pages():
                for i, code in enumerate(BLOCK.findall((DOCS / page).read_text(encoding="utf-8")), start=1):
                    count += 1
                    with self.subTest(page=page, block=i):
                        with contextlib.redirect_stdout(io.StringIO()):
                            exec(compile(code, f"docs/{page} block {i}", "exec"), {"__name__": "__docs__"})
        finally:
            os.chdir(previous)
        self.assertGreaterEqual(count, 12)


class LinkHookTest(unittest.TestCase):
    def rewrite(self, markdown, page="units/cstr.md"):
        return mkdocs_hooks.rewrite_links(markdown, page, REPO_URL + "/")

    def test_link_out_of_docs_goes_to_github(self):
        self.assertEqual(
            self.rewrite("[code](../../src/process_sim_lab/units/cstr.py)"),
            f"[code]({REPO_URL}/blob/main/src/process_sim_lab/units/cstr.py)",
        )
        self.assertEqual(
            self.rewrite("see [it](../README.md#use-from-an-mcp-client)", page="agent.md"),
            f"see [it]({REPO_URL}/blob/main/README.md#use-from-an-mcp-client)",
        )
        self.assertEqual(
            self.rewrite("[cases](../evals/cases/)", page="agent.md"), f"[cases]({REPO_URL}/blob/main/evals/cases)"
        )

    def test_links_inside_docs_and_absolute_links_stay(self):
        for text in ("[a](../agent.md)", "[b](flash.md#examples)", "[c](#model)", "[d](https://example.com/x)",
                     "[e](mailto:someone@example.com)", "[f](../../../outside.md)"):
            with self.subTest(text=text):
                self.assertEqual(self.rewrite(text), text)

    def test_every_page_link_resolves(self):
        """Links inside docs/ point to a page; links out of docs/ point to a file or folder of the repository."""
        link = re.compile(r"\]\((?![a-zA-Z][a-zA-Z0-9+.-]*:|#)([^)\s#]+)")
        for page in doc_pages():
            text = (DOCS / page).read_text(encoding="utf-8")
            for target in link.findall(text):
                with self.subTest(page=page, target=target):
                    self.assertTrue((DOCS / page).parent.joinpath(target).resolve().exists())


@unittest.skipIf(importlib.util.find_spec("mkdocs") is None, "needs the optional extra: pip install -e '.[docs]'")
class StrictBuildTest(unittest.TestCase):
    def test_mkdocs_build_strict(self):
        with tempfile.TemporaryDirectory() as site:
            out = subprocess.run(
                [sys.executable, "-m", "mkdocs", "build", "--strict", "--site-dir", site],
                cwd=ROOT, capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(out.returncode, 0, out.stderr)
            for stem in unit_modules():
                self.assertTrue((Path(site) / "units" / PAGE_OF.get(stem, stem) / "index.html").is_file())


if __name__ == "__main__":
    unittest.main()
