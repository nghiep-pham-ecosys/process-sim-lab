"""MkDocs hook for the docs site: links that leave docs/ point to the file on GitHub.

The pages under docs/ link to the code with relative paths (``../src/process_sim_lab/flowsheet.py``), so they also
work when read on GitHub. Those files are not part of the site, and ``mkdocs build --strict`` fails on a link it
cannot resolve. Before MkDocs reads a page, this hook rewrites every relative link whose target lies outside docs/
(but inside the repository) to ``<repo_url>/blob/main/<path>``. Links inside docs/, absolute URLs and anchors are
left alone. Only ``rewrite_links`` does the work, so the tests run it without MkDocs.
"""

from __future__ import annotations

import posixpath
import re

DOCS_DIR = "docs"
BRANCH = "main"
# A Markdown inline link or image target: ](target) or ](target "title"); targets with a scheme or "#" are skipped.
LINK = re.compile(r"\]\((?![a-zA-Z][a-zA-Z0-9+.-]*:|#|/)([^)\s]+)((?:\s+\"[^\"]*\")?)\)")


def rewrite_links(markdown: str, page: str, repo_url: str) -> str:
    """Rewrite the relative links of one page that leave docs/.

    Args:
        markdown: the page source.
        page: the page path relative to docs/, with forward slashes (for example ``units/cstr.md``).
        repo_url: the repository URL, for example ``https://github.com/owner/repo``.
    """
    base = posixpath.dirname(posixpath.join(DOCS_DIR, page))
    blob = f"{repo_url.rstrip('/')}/blob/{BRANCH}/"

    def replace(match: re.Match[str]) -> str:
        target, title = match.group(1), match.group(2)
        path, hash_, fragment = target.partition("#")
        resolved = posixpath.normpath(posixpath.join(base, path))
        if resolved == ".." or resolved.startswith("../") or resolved.startswith(f"{DOCS_DIR}/"):
            return match.group(0)
        return f"]({blob}{resolved}{hash_}{fragment}{title})"

    return LINK.sub(replace, markdown)


def on_page_markdown(markdown, page, config, files):  # noqa: ANN001, ANN201 (MkDocs hook signature)
    return rewrite_links(markdown, page.file.src_uri, config["repo_url"])
