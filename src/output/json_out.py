"""Write crawl JSON artifacts; crawlers pass the output base directory."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.config.base_logger import get_logger

logger = get_logger()

_SAFE_STEM = re.compile(r"[^a-zA-Z0-9._-]+")


def safe_filename_stem(value: str, *, fallback: str = "item") -> str:
    """Sanitize a string for use as a file or directory stem."""
    stem = _SAFE_STEM.sub("-", value).strip("-") or fallback
    return stem


def ensure_dir(path: str | Path) -> None:
    """Create ``path`` and parents if missing."""
    os.makedirs(path, exist_ok=True)


def write_json(path: str | Path, data: dict[str, Any], *, indent: int = 2) -> Path:
    """Write ``data`` as JSON to ``path``; create parent directories."""
    out = Path(path)
    ensure_dir(out.parent)
    payload = json.dumps(data, indent=indent)
    out.write_text(payload, encoding="utf-8")
    logger.debug("write_json path=%s bytes=%d", out, len(payload.encode("utf-8")))
    return out


def index_page_number(canonical_index_url: str) -> int:
    """1-based page from URL path tail (e.g. ``/profiles/...`` or ``/profiles/.../N``)."""
    path = urlparse(canonical_index_url).path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    if not parts:
        return 1
    tail = parts[-1]
    return int(tail) if tail.isdigit() else 1


def _json_stem_from_path(path: str) -> str:
    """``/profiles/new-york`` -> ``profiles-new-york``; empty -> ``index``."""
    path = (path or "").strip().strip("/")
    if not path:
        return "index"
    stem = "-".join(p for p in path.split("/") if p)
    stem = _SAFE_STEM.sub("-", stem).strip("-") or "index"
    return stem


def index_json_stem(canonical_index_url: str) -> str:
    """Filename stem (no extension) for an index request JSON from its URL."""
    path = urlparse(canonical_index_url).path
    return _json_stem_from_path(path)


def write_index_page_json(
    data_dir: str | Path,
    page_num: int,
    canonical_index_url: str,
    envelope: dict[str, Any],
) -> Path:
    """Write listing index Gaffa envelope JSON under ``data_dir/<page_num>/``."""
    base = Path(data_dir)
    ensure_dir(base)
    stem = index_json_stem(canonical_index_url)
    out_dir = base / str(page_num)
    return write_json(out_dir / f"{stem}.json", envelope)


def write_provider_page_json(
    data_dir: str | Path,
    page_num: int,
    provider_slug: str,
    envelope: dict[str, Any],
) -> Path:
    """Write provider Gaffa envelope JSON under ``data_dir/<page_num>/<slug>/``."""
    base = Path(data_dir)
    ensure_dir(base)
    safe = _SAFE_STEM.sub("-", provider_slug).strip("-") or "provider"
    out_dir = base / str(page_num) / safe
    return write_json(out_dir / f"{safe}.json", envelope)
