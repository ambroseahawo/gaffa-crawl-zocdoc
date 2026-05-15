"""Scrap Zocdoc via Gaffa browser automation
python -m src.crawlers.profiles
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass

import aiohttp

from src.api_requests.client import (
    DEFAULT_API_BASE,
    GaffaClientOptions,
    run_browser_request_to_completion,
)
from src.config.base_logger import get_logger
from src.config.constants import MAX_PROVIDERS_PER_LISTING, TIME_LIMIT_MS, ZOCDOC_ORIGIN
from src.config.env import GAFFA_API_KEY, gaffa_concurrency_settings
from src.output.json_out import (
    index_page_number,
    write_index_page_json,
    write_provider_page_json,
)
from src.processors.envelope import capture_dom_output_url, gaffa_envelope_json
from src.processors.provider_links import (
    profile_index_pagination_hrefs,
    provider_hrefs_from_html,
    provider_slug_from_url,
    zocdoc_provider_urls,
)

logger = get_logger()


def _effective_max_providers_per_listing() -> int | None:
    """``MAX_PROVIDERS_PER_LISTING``: cap per listing page; ``None``/``<=0`` = unlimited."""
    v = MAX_PROVIDERS_PER_LISTING
    return v if v is not None and v > 0 else None


@dataclass(frozen=True, slots=True)
class GaffaHttp:
    """Shared aiohttp session + Gaffa credentials and concurrency limiter."""

    session: aiohttp.ClientSession
    api_key: str
    options: GaffaClientOptions
    gaffa_sem: asyncio.Semaphore


@dataclass
class CrawlState:
    """crawler state"""

    queue: deque[str]
    seen: set[str]


def browse_request_body(url: str) -> dict:
    """
    Browser request input (url, proxy_location, async, max_cache_age, settings) per
    POST /v1/browser/requests OpenAPI schema; actions per browser-requests docs.
    """
    return {
        "url": url,
        "proxy_location": "us",
        "async": True,
        "max_cache_age": 0,
        "settings": {
            "time_limit": TIME_LIMIT_MS,
            "record_request": True,
            "actions": [
                {"type": "wait", "time": 8000},
                {
                    "type": "scroll",
                    "percentage": 100,
                    "scroll_speed": "medium",
                    "wait_time": 2000,
                    "max_scroll_time": 20000,
                },
                {"type": "wait", "time": 4000},
                {"type": "capture_dom"},
            ],
        },
    }


def canonical_index_url(url: str) -> str:
    """canonicalize index url"""
    resolved = zocdoc_provider_urls([url], origin=ZOCDOC_ORIGIN)
    return resolved[0] if resolved else url


async def browse_capture_envelope(
    session: aiohttp.ClientSession,
    api_key: str,
    url: str,
    options: GaffaClientOptions,
    *,
    gaffa_sem: asyncio.Semaphore,
) -> dict:
    """Run browse+scroll+capture_dom for ``url``; return the raw Gaffa JSON envelope.

    ``gaffa_sem`` caps concurrent Gaffa browser runs: many tasks may exist, but only
    ``gaffa_sem``'s initial value run inside ``async with`` at once. Each active run
    emits ``gaffa request start url=`` from ``run_browser_request_to_completion``.
    """
    async with gaffa_sem:
        body = browse_request_body(url)
        _, debug_envelope = await run_browser_request_to_completion(session, api_key, body, options)
    return debug_envelope


async def fetch_profile_index_html(
    session: aiohttp.ClientSession,
    api_key: str,
    page_url: str,
    options: GaffaClientOptions,
    *,
    gaffa_sem: asyncio.Semaphore,
) -> tuple[dict, str]:
    """Profile index: same browser run as providers, plus download ``capture_dom`` HTML."""
    debug_envelope = await browse_capture_envelope(
        session, api_key, page_url, options, gaffa_sem=gaffa_sem
    )
    dom_url = capture_dom_output_url(debug_envelope)
    if not dom_url:
        raise RuntimeError(gaffa_envelope_json(debug_envelope))
    async with session.get(dom_url) as resp:
        resp.raise_for_status()
        index_html = await resp.text()
    logger.info("index HTML OK bytes=%d url=%s", len(index_html), page_url)
    return debug_envelope, index_html


def enqueue_pagination_links(queue: deque[str], seen: set[str], html: str) -> None:
    """enqueue pagination links"""
    for ph in profile_index_pagination_hrefs(html):
        for absolute in zocdoc_provider_urls([ph], origin=ZOCDOC_ORIGIN):
            nk = canonical_index_url(absolute)
            if nk not in seen:
                queue.append(absolute)


def pop_next_index_batch(
    queue: deque[str],
    seen: set[str],
    *,
    max_items: int,
) -> list[tuple[str, str]]:
    """Up to ``max_items`` unseen (canonical_key, page_url) pairs; keys are marked seen."""
    batch: list[tuple[str, str]] = []
    limit = max_items
    while len(batch) < limit and queue:
        page_url = queue.popleft()
        key = canonical_index_url(page_url)
        if key in seen:
            continue
        seen.add(key)
        batch.append((key, page_url))
    return batch


async def _fetch_and_write_provider(
    http: GaffaHttp,
    provider_url: str,
    page_num: int,
    slug: str,
) -> None:
    try:
        prov_env = await browse_capture_envelope(http.session, http.api_key, provider_url, http.options, gaffa_sem=http.gaffa_sem)
        prov_path = write_provider_page_json(page_num, slug, prov_env)
        logger.debug("provider OK page=%s slug=%s path=%s", page_num, slug, prov_path)
    except (OSError, TimeoutError, RuntimeError, aiohttp.ClientError, TypeError, ValueError) as exc:
        logger.warning("provider FAIL page=%s slug=%s url=%s: %s", page_num, slug, provider_url, exc)


async def _gather_ok_index_rows(
    http: GaffaHttp,
    batch: list[tuple[str, str]],
) -> list[tuple[str, str, dict, str]]:
    index_tasks = [fetch_profile_index_html(http.session, http.api_key, page_url, http.options, gaffa_sem=http.gaffa_sem) for _key, page_url in batch]
    index_results = await asyncio.gather(*index_tasks, return_exceptions=True)
    ok_rows: list[tuple[str, str, dict, str]] = []
    for (key, page_url), outcome in zip(batch, index_results):
        if isinstance(outcome, BaseException):
            logger.warning("index FAIL url=%s: %s", page_url, outcome)
            continue
        env, html = outcome
        ok_rows.append((key, page_url, env, html))
    return ok_rows


def _schedule_provider_tasks(
    http: GaffaHttp,
    ok_rows: list[tuple[str, str, dict, str]],
) -> tuple[list[asyncio.Task[None]], list[tuple[int, str, int, int]]]:
    all_provider_jobs: list[asyncio.Task[None]] = []
    page_stats: list[tuple[int, str, int, int]] = []
    cap = _effective_max_providers_per_listing()
    hit_cap = False

    for key, _page_url, env, html in ok_rows:
        page_num = index_page_number(key)
        index_path = write_index_page_json(page_num, key, env)
        logger.info("index JSON page=%s path=%s", page_num, index_path)

        page_urls = zocdoc_provider_urls(provider_hrefs_from_html(html), origin=ZOCDOC_ORIGIN)
        seen_slugs: set[str] = set()
        row_scheduled = 0

        for provider_url in page_urls:
            slug = provider_slug_from_url(provider_url)
            if not slug or slug in seen_slugs:
                continue
            if cap is not None and row_scheduled >= cap:
                hit_cap = True
                break
            seen_slugs.add(slug)
            row_scheduled += 1
            all_provider_jobs.append(asyncio.create_task(_fetch_and_write_provider(http, provider_url, page_num, slug)))
        page_stats.append((page_num, key, len(page_urls), len(seen_slugs)))

    if hit_cap and cap is not None:
        logger.info("provider schedule hit per-listing cap=%d", cap)
    return all_provider_jobs, page_stats


def _log_index_batch_stats(page_stats: list[tuple[int, str, int, int]]) -> None:
    for page_num, key, n_urls, n_slugs in page_stats:
        logger.info(
            "index summary page=%s hrefs=%d providers_scheduled=%d key=%s",
            page_num,
            n_urls,
            n_slugs,
            key,
        )


def _enqueue_pagination_for_rows(state: CrawlState, ok_rows: list[tuple[str, str, dict, str]]) -> None:
    for _key, _page_url, _env, html in ok_rows:
        enqueue_pagination_links(state.queue, state.seen, html)


async def crawl_profile_indexes(api_key: str) -> None:
    """Crawl every profile-list URL discovered via pagination until the queue is empty."""
    target_url = "https://www.zocdoc.com/profiles/new-york"
    options = GaffaClientOptions(base_url=DEFAULT_API_BASE)
    index_batch, sem_slots = gaffa_concurrency_settings()
    gaffa_sem = asyncio.Semaphore(sem_slots)
    state = CrawlState(deque([target_url]), set())
    cap_display = _effective_max_providers_per_listing()
    logger.info(
        "crawl start seed=%s index_batch=%d gaffa_slots=%d queue=%d max_providers_per_listing=%s",
        target_url,
        index_batch,
        sem_slots,
        len(state.queue),
        cap_display if cap_display is not None else "unlimited",
    )
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600)) as session:
        http = GaffaHttp(session, api_key, options, gaffa_sem)
        cycle = 0
        while state.queue:
            batch = pop_next_index_batch(
                state.queue,
                state.seen,
                max_items=index_batch,
            )
            if not batch:
                break

            cycle += 1
            batch_urls = [u for _k, u in batch]
            logger.info("cycle=%d index fetch count=%d urls=%s", cycle, len(batch_urls), batch_urls)
            ok_rows = await _gather_ok_index_rows(http, batch)
            provider_tasks, page_stats = _schedule_provider_tasks(http, ok_rows)
            logger.info(
                "cycle=%d provider scheduled=%d concurrent_limit=%d",
                cycle,
                len(provider_tasks),
                sem_slots,
            )
            if provider_tasks:
                await asyncio.gather(*provider_tasks)
                logger.info("cycle=%d provider batch done", cycle)
            _log_index_batch_stats(page_stats)
            _enqueue_pagination_for_rows(state, ok_rows)
            logger.info(
                "cycle=%d done queue=%d seen=%d",
                cycle,
                len(state.queue),
                len(state.seen),
            )
        logger.info("crawl finished (queue empty or drained)")


async def main() -> None:
    """Crawl profile index pages via Gaffa."""
    api_key = GAFFA_API_KEY
    if not api_key:
        logger.error("GAFFA_API_KEY is not set.")
        raise RuntimeError("GAFFA_API_KEY is not set.")
    logger.info("profiles module starting")
    await crawl_profile_indexes(api_key)


if __name__ == "__main__":
    asyncio.run(main())
