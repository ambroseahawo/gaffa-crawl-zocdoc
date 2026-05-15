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
from dataclasses import dataclass, replace
from typing import Any

import aiohttp

from src.config.base_logger import get_logger
from src.config.constants import DEFAULT_API_BASE, TERMINAL_STATES, TOTAL_ATTEMPTS
from src.processors.envelope import capture_dom_output_url, gaffa_envelope_json

logger = get_logger()


@dataclass(frozen=True, slots=True)
class GaffaClientOptions:
    """Base URL, polling, and retry settings for browser requests."""

    base_url: str = DEFAULT_API_BASE
    poll_interval_sec: float = 2.0
    poll_max_attempts: int = 90
    total_attempts: int = TOTAL_ATTEMPTS
    target_url: str = ""
    request_attempt: int = 1


def _http_error(method: str, status: int, raw: bytes) -> str:
    text = raw.decode(errors="replace").strip()
    if text.startswith("<"):
        return f"Gaffa {method} {status}"
    try:
        body = json.loads(text)
        if isinstance(body, dict):
            return gaffa_envelope_json(body)
    except json.JSONDecodeError:
        pass
    return f"Gaffa {method} {status}"


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
            raise RuntimeError(_http_error("POST", resp.status, raw))
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
            raise RuntimeError(_http_error("GET", resp.status, raw))
        envelope: dict[str, Any] = json.loads(raw.decode()) if raw else {}
    return unwrap_browser_request(envelope), envelope


async def poll_browser_request_until_terminal(
    session: aiohttp.ClientSession,
    api_key: str,
    request_id: str,
    options: GaffaClientOptions | None = None,
) -> tuple[dict[str, Any], dict[str, Any], int]:
    """
    Poll GET /v1/browser/requests/{id} until `state` is completed or failed.
    Returns (inner_resource, last_raw_envelope, poll_attempts for this request_attempt).
    """
    cfg = options or GaffaClientOptions()
    last_envelope: dict[str, Any] = {}
    last_state: str | None = None
    url_bit = f" url={cfg.target_url}" if cfg.target_url else ""
    poll_attempts = 0
    for poll_idx in range(cfg.poll_max_attempts):
        poll_attempt = poll_idx + 1
        poll_attempts = poll_attempt
        inner, last_envelope = await get_browser_request(session, api_key, request_id, base_url=cfg.base_url)
        state = (inner.get("state") or "").lower()
        if state != last_state:
            logger.info(
                "gaffa poll id=%s%s state=%s request_attempt=%s poll_attempt=%s/%s",
                request_id,
                url_bit,
                state or "?",
                cfg.request_attempt,
                poll_attempt,
                cfg.poll_max_attempts,
            )
            last_state = state
        elif poll_idx > 0 and poll_attempt % 15 == 0:
            logger.info(
                "gaffa poll id=%s%s still %s request_attempt=%s poll_attempt=%s/%s",
                request_id,
                url_bit,
                state or "?",
                cfg.request_attempt,
                poll_attempt,
                cfg.poll_max_attempts,
            )
        if state in TERMINAL_STATES:
            if state == "failed":
                logger.info(
                    "gaffa request failed id=%s%s request_attempt=%s poll_attempts=%s",
                    request_id,
                    url_bit,
                    cfg.request_attempt,
                    poll_attempts,
                )
                raise RuntimeError(gaffa_envelope_json(last_envelope))
            if state == "completed" and not capture_dom_output_url(last_envelope):
                poll_attempts += 1
                inner, last_envelope = await get_browser_request(session, api_key, request_id, base_url=cfg.base_url)
            logger.info(
                "gaffa request completed id=%s%s request_attempt=%s poll_attempts=%s",
                request_id,
                url_bit,
                cfg.request_attempt,
                poll_attempts,
            )
            return inner, last_envelope, poll_attempts
        await asyncio.sleep(cfg.poll_interval_sec)
    logger.error(
        "gaffa poll timeout id=%s%s request_attempt=%s poll_attempts=%s",
        request_id,
        url_bit,
        cfg.request_attempt,
        cfg.poll_max_attempts,
    )
    raise TimeoutError(f"Gaffa request {request_id} did not reach a terminal state after polling.")


async def _run_browser_request_once(
    session: aiohttp.ClientSession,
    api_key: str,
    body: dict[str, Any],
    options: GaffaClientOptions | None = None,
    *,
    request_attempt: int = 1,
) -> tuple[dict[str, Any], dict[str, Any], int]:
    """
    POST a browser request, then poll until completed/failed if not already terminal.

    Returns (inner_resource, debug_envelope) where debug_envelope is the last JSON
    envelope useful for logging (initial POST body if already completed, else last GET).
    """
    opts = options or GaffaClientOptions()
    target_url = str(body.get("url") or "")
    url_bit = f" url={target_url}" if target_url else ""
    logger.info("gaffa request start%s request_attempt=%s", url_bit, request_attempt)
    inner, post_envelope = await post_browser_request(session, api_key, body, base_url=opts.base_url)
    request_id = inner.get("id")
    if not request_id:
        raise RuntimeError(f"Gaffa did not return request id: {post_envelope!r}")

    state = (inner.get("state") or "").lower()
    poll_attempts = 0
    if state == "failed":
        logger.info(
            "gaffa request failed id=%s%s request_attempt=%s poll_attempts=%s",
            request_id,
            url_bit,
            request_attempt,
            poll_attempts,
        )
        raise RuntimeError(gaffa_envelope_json(post_envelope))
    if state == "completed":
        if not capture_dom_output_url(post_envelope):
            poll_attempts = 1
            inner, post_envelope = await get_browser_request(session, api_key, request_id, base_url=opts.base_url)
        logger.info(
            "gaffa request completed id=%s%s request_attempt=%s poll_attempts=%s",
            request_id,
            url_bit,
            request_attempt,
            poll_attempts,
        )
        return inner, post_envelope, poll_attempts

    poll_opts = replace(opts, target_url=target_url, request_attempt=request_attempt)
    inner, last, poll_attempts = await poll_browser_request_until_terminal(session, api_key, request_id, poll_opts)
    return inner, last, poll_attempts


async def _browser_request_with_dom_retries(
    session: aiohttp.ClientSession,
    api_key: str,
    body: dict[str, Any],
    opts: GaffaClientOptions,
) -> tuple[dict[str, Any], dict[str, Any]]:
    target_url = str(body.get("url") or "")
    url_bit = f" url={target_url}" if target_url else ""
    total = max(1, opts.total_attempts)
    last_exc: BaseException | None = None
    for attempt in range(total):
        request_attempt = attempt + 1
        try:
            inner, envelope, poll_attempts = await _run_browser_request_once(session, api_key, body, opts, request_attempt=request_attempt)
            if not capture_dom_output_url(envelope):
                logger.info(
                    "gaffa request failed%s request_attempt=%s poll_attempts=%s",
                    url_bit,
                    request_attempt,
                    poll_attempts,
                )
                raise RuntimeError(gaffa_envelope_json(envelope))
            logger.info(
                "gaffa done%s request_attempt=%s poll_attempts=%s",
                url_bit,
                request_attempt,
                poll_attempts,
            )
            return inner, envelope
        except (RuntimeError, TimeoutError, aiohttp.ClientError, OSError) as exc:
            last_exc = exc
            final = request_attempt >= total
            logger.warning(
                "gaffa request_attempt %s/%s failed%s: %s",
                request_attempt,
                total,
                url_bit,
                exc,
            )
            if final:
                raise
            await asyncio.sleep(min(2**attempt, 30))
    raise last_exc  # pragma: no cover


async def run_browser_request_to_completion(
    session: aiohttp.ClientSession,
    api_key: str,
    body: dict[str, Any],
    options: GaffaClientOptions | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    POST + poll until ``capture_dom`` has an HTTP ``output`` URL (DOM text on Gaffa storage).

    Retries up to ``total_attempts`` whenever that URL is missing or the HTTP/poll path raises.
    """
    opts = options or GaffaClientOptions()
    return await _browser_request_with_dom_retries(session, api_key, body, opts)
