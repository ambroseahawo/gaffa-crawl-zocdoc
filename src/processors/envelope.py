"""Read fields from Gaffa browser-request JSON envelopes."""

from __future__ import annotations

import json
from typing import Any

from src.config.base_logger import get_logger

logger = get_logger()


def gaffa_envelope_json(envelope: Any) -> str:
    """JSON for logs — same parsed object shape the API returned"""
    try:
        return json.dumps(envelope, default=str)
    except (TypeError, ValueError):
        return repr(envelope)


def _action_blocks(envelope: dict[str, Any]) -> list[list[Any]]:
    blocks: list[list[Any]] = []
    data = envelope.get("data")
    if isinstance(data, dict):
        blocks.append(data.get("actions") or [])
    blocks.append(envelope.get("actions") or [])
    return blocks


def _capture_dom_output_from_action(action: dict[str, Any]) -> str | None:
    for key in ("output", "Output", "output_url", "outputUrl"):
        out = action.get(key)
        if isinstance(out, str) and out.strip().startswith(("http://", "https://")):
            return out.strip()
    return None


def capture_dom_output_url(envelope: dict[str, Any]) -> str | None:
    """First ``capture_dom`` action URL from ``envelope`` (`data.actions` or top-level ``actions``)."""
    if not isinstance(envelope, dict):
        logger.warning("capture_dom_output_url: envelope is not a dict (%r)", type(envelope).__name__)
        return None
    for actions in _action_blocks(envelope):
        for action in actions:
            if not isinstance(action, dict):
                continue
            t = (action.get("type") or "").lower().replace("-", "").replace("_", "")
            if t != "capturedom":
                continue
            out = _capture_dom_output_from_action(action)
            if out:
                return out
    logger.debug("capture_dom_output_url: no capture_dom HTTP output URL in envelope yet")
    return None


def capture_dom_action_output_url(action: dict[str, Any]) -> str | None:
    """HTTP URL for a single ``capture_dom`` action output."""
    return _capture_dom_output_from_action(action)


def capture_dom_actions(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    """All completed ``capture_dom`` actions that have an HTTP ``output`` URL."""
    if not isinstance(envelope, dict):
        return []
    found: list[dict[str, Any]] = []
    for actions in _action_blocks(envelope):
        for action in actions:
            if not isinstance(action, dict):
                continue
            t = (action.get("type") or "").lower().replace("-", "").replace("_", "")
            if t != "capturedom":
                continue
            if _capture_dom_output_from_action(action):
                found.append(action)
    return found
