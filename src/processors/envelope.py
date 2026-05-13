"""Read fields from Gaffa browser-request JSON envelopes."""

from __future__ import annotations

from typing import Any

from src.config.base_logger import get_logger

logger = get_logger()


def capture_dom_output_url(envelope: dict[str, Any]) -> str | None:
    """First ``capture_dom`` action URL from ``envelope`` (`data.actions` or top-level ``actions``)."""
    if not isinstance(envelope, dict):
        logger.warning("capture_dom_output_url: envelope is not a dict (%r)", type(envelope).__name__)
        return None
    blocks: list[list[Any]] = []
    data = envelope.get("data")
    if isinstance(data, dict):
        blocks.append(data.get("actions") or [])
    blocks.append(envelope.get("actions") or [])

    for actions in blocks:
        for action in actions:
            if not isinstance(action, dict):
                continue
            t = (action.get("type") or "").lower().replace("-", "").replace("_", "")
            if t != "capturedom":
                continue
            for key in ("output", "Output", "output_url", "outputUrl"):
                out = action.get(key)
                if isinstance(out, str) and out.strip().startswith(("http://", "https://")):
                    return out.strip()
    logger.debug("capture_dom_output_url: no capture_dom HTTP output URL in envelope yet")
    return None
