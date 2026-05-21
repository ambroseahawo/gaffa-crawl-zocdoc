"""Scrap Monster job search listings via Gaffa browser automation.

python -m src.crawlers.monster.jobs
"""

from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, unquote_plus, urlencode, urlparse, urlunparse

import aiohttp

from src.api_requests.client import (
    DEFAULT_API_BASE,
    GaffaClientOptions,
    run_browser_request_to_completion,
)
from src.config.base_logger import get_logger
from src.config.constants import TIME_LIMIT_MS
from src.config.env import GAFFA_API_KEY
from src.crawlers.monster.constants import (
    JOBS_DATA_DIR,
    JOBS_SEED_URL,
    MAX_LISTING_PAGES,
    MIN_JOB_CARDS,
)
from src.crawlers.monster.parsers import job_card_count, page_num_from_listing_html
from src.output.json_out import safe_filename_stem, write_json
from src.processors.envelope import capture_dom_output_url

logger = get_logger()


def browse_request_body(url: str, *, time_limit_ms: int | None = TIME_LIMIT_MS) -> dict:
    """Gaffa actions compatible with this plan (no ``selector`` / ``customId``)."""
    return {
        "url": url,
        "proxy_location": "us",
        "async": True,
        "max_cache_age": 0,
        "settings": {
            "time_limit": time_limit_ms,
            "record_request": True,
            "actions": [
                {"type": "wait", "time": 10000},
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


def query_stem_from_url(url: str) -> str:
    """Filesystem stem from the search ``q`` query parameter."""
    qs = parse_qs(urlparse(url).query)
    raw = (qs.get("q") or [""])[0]
    return safe_filename_stem(unquote_plus(raw), fallback="search")


def page_num_from_url(url: str) -> int:
    """1-based page number from the ``page`` query parameter."""
    qs = parse_qs(urlparse(url).query)
    try:
        return max(1, int((qs.get("page") or ["1"])[0] or 1))
    except ValueError:
        return 1


def search_url_with_page(seed_url: str, page_num: int) -> str:
    """Same search URL with an updated ``page`` query parameter."""
    parsed = urlparse(seed_url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs["page"] = [str(max(1, page_num))]
    query = urlencode(qs, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment))


def build_page_envelope(full_envelope: dict, *, page_url: str) -> dict:
    """Envelope with ``data.url`` set to the listing page URL."""
    data = full_envelope.get("data")
    if not isinstance(data, dict):
        return {"data": {"url": page_url}}
    return {**full_envelope, "data": {**data, "url": page_url}}


async def _download_dom(session: aiohttp.ClientSession, url: str) -> str:
    async with session.get(url) as resp:
        resp.raise_for_status()
        return await resp.text()


def _verify_job_cards(html: str, *, page_url: str, page_num: int) -> None:
    count = job_card_count(html)
    dom_page = page_num_from_listing_html(html)
    if dom_page is not None and dom_page != page_num:
        logger.warning(
            "listing page mismatch url_page=%s dom_page=%s url=%s",
            page_num,
            dom_page,
            page_url,
        )
    if page_num == 1 and count < MIN_JOB_CARDS:
        logger.warning(
            "listing page=%s has %d job cards (expected >= %d) url=%s",
            page_num,
            count,
            MIN_JOB_CARDS,
            page_url,
        )
    else:
        logger.info("listing page=%s job_cards=%d url=%s", page_num, count, page_url)


async def fetch_listing_page(
    session: aiohttp.ClientSession,
    api_key: str,
    page_url: str,
    options: GaffaClientOptions,
) -> dict:
    """Fetch one search results page via Gaffa."""
    body = browse_request_body(page_url)
    _, envelope = await run_browser_request_to_completion(session, api_key, body, options)
    return envelope


async def crawl_job_listings(
    api_key: str,
    *,
    seed_url: str = JOBS_SEED_URL,
    max_pages: int = MAX_LISTING_PAGES,
) -> None:
    """Fetch each ``page=N`` search URL and write ``pageN.json`` (Gaffa plan: no action selectors)."""
    query_stem = query_stem_from_url(seed_url)
    pages = max(1, max_pages)
    logger.info("crawl start seed=%s max_pages=%d", seed_url, pages)

    options = GaffaClientOptions(base_url=DEFAULT_API_BASE)
    saved_paths: list[str] = []

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600)) as session:
        for page_num in range(1, pages + 1):
            page_url = search_url_with_page(seed_url, page_num)
            logger.info("listing fetch page=%s url=%s", page_num, page_url)
            envelope = await fetch_listing_page(session, api_key, page_url, options)
            page_envelope = build_page_envelope(envelope, page_url=page_url)
            out_path = write_json(
                f"{JOBS_DATA_DIR}/{query_stem}/page{page_num}.json",
                page_envelope,
            )
            saved_paths.append(str(out_path))
            logger.info("listing JSON page=%s path=%s", page_num, out_path)

            dom_url = capture_dom_output_url(envelope)
            if dom_url:
                html = await _download_dom(session, dom_url)
                _verify_job_cards(html, page_url=page_url, page_num=page_num)

    logger.info("crawl done saved=%d paths=%s", len(saved_paths), saved_paths)


async def main() -> None:
    """Fetch Monster job search listing pages via Gaffa."""
    api_key = GAFFA_API_KEY
    if not api_key:
        logger.error("GAFFA_API_KEY is not set.")
        raise RuntimeError("GAFFA_API_KEY is not set.")
    logger.info("monster jobs starting")
    await crawl_job_listings(api_key)


if __name__ == "__main__":
    asyncio.run(main())
