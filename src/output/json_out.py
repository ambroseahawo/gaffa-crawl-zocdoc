"""Write crawl artifacts under ``gaffa/data/<page>/``."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.config.base_logger import get_logger
from src.config.constants import DATA_DIR

logger = get_logger()

_SAFE_STEM = re.compile(r"[^a-zA-Z0-9._-]+")


def _ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def index_page_number(canonical_profile_index_url: str) -> int:
    """1-based page from path ``/profiles/...`` or ``/profiles/.../N``."""
    path = urlparse(canonical_profile_index_url).path.rstrip("/")
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


def index_json_stem(canonical_profile_index_url: str) -> str:
    """Filename stem (no extension) for the profile-index request JSON from its URL."""
    path = urlparse(canonical_profile_index_url).path
    return _json_stem_from_path(path)


def write_index_page_json(page_num: int, canonical_profile_index_url: str, envelope: dict[str, Any]) -> Path:
    """write index page json"""
    _ensure_data_dir()
    stem = index_json_stem(canonical_profile_index_url)
    out_dir = os.path.join(DATA_DIR, str(page_num))
    os.makedirs(out_dir, exist_ok=True)
    path_str = os.path.join(out_dir, f"{stem}.json")
    payload = json.dumps(envelope, indent=2)
    path = Path(path_str)
    path.write_text(payload, encoding="utf-8")
    logger.debug("write_index_page_json path=%s bytes=%d", path, len(payload.encode("utf-8")))
    return path


def write_provider_page_json(page_num: int, provider_slug: str, envelope: dict[str, Any]) -> Path:
    """write provider page json"""
    _ensure_data_dir()
    safe = _SAFE_STEM.sub("-", provider_slug).strip("-") or "provider"
    out_dir = os.path.join(DATA_DIR, str(page_num), safe)
    os.makedirs(out_dir, exist_ok=True)
    path_str = os.path.join(out_dir, f"{safe}.json")
    payload = json.dumps(envelope, indent=2)
    path = Path(path_str)
    path.write_text(payload, encoding="utf-8")
    logger.debug("write_provider_page_json path=%s bytes=%d", path, len(payload.encode("utf-8")))
    return path
