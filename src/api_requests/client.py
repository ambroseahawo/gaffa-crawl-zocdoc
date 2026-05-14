"""
Gaffa Browser Requests HTTP client.

API surface (OpenAPI / public docs):
  - POST https://api.gaffa.dev/v1/browser/requests — create request (sync or async).
  - GET  https://api.gaffa.dev/v1/browser/requests/{id} — fetch by id (polling).
  - Auth: header X-API-Key.
  - Terminal states (bulk GET docs): pending, running, completed, failed.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import aiohttp

from src.config.base_logger import get_logger
from src.config.constants import DEFAULT_API_BASE, TERMINAL_STATES
from src.processors.envelope import capture_dom_output_url, gaffa_envelope_json

logger = get_logger()


@dataclass(frozen=True, slots=True)
class GaffaClientOptions:
    """Base URL and polling tuning for browser requests."""

    base_url: str = DEFAULT_API_BASE
    poll_interval_sec: float = 2.0
    poll_max_attempts: int = 90


def unwrap_browser_request(envelope: dict[str, Any]) -> dict[str, Any]:
    """Responses may nest the resource under `data` or return it at top level."""
    inner = envelope.get("data")
    if isinstance(inner, dict) and any(k in inner for k in ("id", "state", "actions", "url")):
        return inner
    return envelope


async def post_browser_request(
    session: aiohttp.ClientSession,
    api_key: str,
    body: dict[str, Any],
    *,
    base_url: str = DEFAULT_API_BASE,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    POST /v1/browser/requests.
    Returns (inner_resource, raw_json_envelope).
    """
    url = f"{base_url.rstrip('/')}/v1/browser/requests"
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    async with session.post(url, json=body, headers=headers) as resp:
        raw = await resp.read()
        if resp.status >= 400:
            raise RuntimeError(f"Gaffa POST {resp.status}: {raw.decode(errors='replace')}")
        envelope: dict[str, Any] = json.loads(raw.decode()) if raw else {}
    return unwrap_browser_request(envelope), envelope


async def get_browser_request(
    session: aiohttp.ClientSession,
    api_key: str,
    request_id: str,
    *,
    base_url: str = DEFAULT_API_BASE,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    GET /v1/browser/requests/{id}.
    Returns (inner_resource, raw_json_envelope).
    """
    url = f"{base_url.rstrip('/')}/v1/browser/requests/{request_id}"
    headers = {"X-API-Key": api_key}
    async with session.get(url, headers=headers) as resp:
        raw = await resp.read()
        if resp.status >= 400:
            raise RuntimeError(f"Gaffa GET {resp.status}: {raw.decode(errors='replace')}")
        envelope: dict[str, Any] = json.loads(raw.decode()) if raw else {}
    return unwrap_browser_request(envelope), envelope


async def poll_browser_request_until_terminal(
    session: aiohttp.ClientSession,
    api_key: str,
    request_id: str,
    options: GaffaClientOptions | None = None,
    *,
    target_url: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Poll GET /v1/browser/requests/{id} until `state` is completed or failed.
    Returns (inner_resource, last_raw_envelope).
    """
    cfg = options or GaffaClientOptions()
    last_envelope: dict[str, Any] = {}
    last_state: str | None = None
    url_bit = f" url={target_url}" if target_url else ""
    for attempt in range(cfg.poll_max_attempts):
        inner, last_envelope = await get_browser_request(session, api_key, request_id, base_url=cfg.base_url)
        state = (inner.get("state") or "").lower()
        if state != last_state:
            logger.info("gaffa poll id=%s%s state=%s", request_id, url_bit, state or "?")
            last_state = state
        elif attempt > 0 and (attempt + 1) % 15 == 0:
            logger.info(
                "gaffa poll id=%s%s still %s (%s/%s)",
                request_id,
                url_bit,
                state or "?",
                attempt + 1,
                cfg.poll_max_attempts,
            )
        if state in TERMINAL_STATES:
            if state == "failed":
                raise RuntimeError(f"Browser request failed: {gaffa_envelope_json(last_envelope)}")
            if state == "completed" and not capture_dom_output_url(last_envelope):
                inner, last_envelope = await get_browser_request(session, api_key, request_id, base_url=cfg.base_url)
            return inner, last_envelope
        await asyncio.sleep(cfg.poll_interval_sec)
    logger.error(
        "gaffa poll timeout id=%s%s after %s attempts",
        request_id,
        url_bit,
        cfg.poll_max_attempts,
    )
    raise TimeoutError(f"Gaffa request {request_id} did not reach a terminal state after polling.")


async def run_browser_request_to_completion(
    session: aiohttp.ClientSession,
    api_key: str,
    body: dict[str, Any],
    options: GaffaClientOptions | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    POST a browser request, then poll until completed/failed if not already terminal.

    Returns (inner_resource, debug_envelope) where debug_envelope is the last JSON
    envelope useful for logging (initial POST body if already completed, else last GET).
    """
    opts = options or GaffaClientOptions()
    target_url = str(body.get("url") or "")
    logger.info("gaffa request start url=%s", target_url)
    inner, post_envelope = await post_browser_request(session, api_key, body, base_url=opts.base_url)
    request_id = inner.get("id")
    if not request_id:
        raise RuntimeError(f"Gaffa did not return request id: {post_envelope!r}")

    state = (inner.get("state") or "").lower()
    logger.info("gaffa request id=%s state=%s", request_id, state or "?")
    if state == "failed":
        raise RuntimeError(f"Browser request failed immediately: {gaffa_envelope_json(post_envelope)}")
    if state == "completed":
        if not capture_dom_output_url(post_envelope):
            inner, post_envelope = await get_browser_request(session, api_key, request_id, base_url=opts.base_url)
        logger.info("gaffa request done id=%s state=completed", request_id)
        return inner, post_envelope

    inner, last = await poll_browser_request_until_terminal(
        session, api_key, request_id, options=opts, target_url=target_url
    )
    logger.info(
        "gaffa request done id=%s state=%s",
        request_id,
        (inner.get("state") or "").lower() or "?",
    )
    return inner, last
