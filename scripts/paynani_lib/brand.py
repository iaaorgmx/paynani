"""
The mark, inlined into the page. Port of webapp/lib/brand.php.

brand/ is the single source of truth for the logo and lives at the top of the
clone, outside any docroot this server exposes, so the page cannot link to
it — and does not want to: server.py serves `default-src 'none'` with no
`img-src`, so an <img> would be blocked, and a page that collects a mail
password is the wrong place to widen a policy for the sake of a picture.
Inline markup is not a fetched resource, so it needs no directive at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness"))
from paths import repo_root  # noqa: E402

# The files this page may inline, by their own names. A list rather than a
# check: the argument never comes from a request today, and an allowlist
# means it still cannot name a path if that ever changes.
BRAND_FILES = (
    "paynani-horizontal.svg",
    "paynani-vertical.svg",
    "voluta.svg",
    "voluta-reducida.svg",
)


def brand_svg(name: str) -> str:
    """The SVG source, ready to drop into the markup, or an empty string. Empty
    rather than an error: a missing logo is a page without a logo."""
    if name not in BRAND_FILES:
        return ""
    file = repo_root() / "brand" / name
    try:
        return file.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
