"""Monster listing HTML helpers."""

from __future__ import annotations

import json
import re

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>',
    re.DOTALL,
)


def job_card_count(html: str) -> int:
    """Count ``data-testid=\"JobCard\"`` entries in listing HTML."""
    return (html or "").count('data-testid="JobCard"')


def page_num_from_listing_html(html: str) -> int | None:
    """Read ``page`` from ``__NEXT_DATA__.props.pageProps.urlParameters``."""
    match = _NEXT_DATA_RE.search(html or "")
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    page_props = payload.get("props", {}).get("pageProps", {})
    url_params = page_props.get("urlParameters") or {}
    raw = url_params.get("page")
    if raw is None:
        return None
    try:
        return max(1, int(str(raw)))
    except ValueError:
        return None
