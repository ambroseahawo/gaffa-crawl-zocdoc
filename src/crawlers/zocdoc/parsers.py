"""Zocdoc HTML parsing and URL helpers."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.config.base_logger import get_logger
from src.crawlers.zocdoc.constants import ZOCDOC_ORIGIN

logger = get_logger()

_PAGE_LINK_TEST = re.compile(r"^\d+-page$")
# Below this size, missing links are treated as normal (empty shell pages, errors).
_SUBSTANTIVE_HTML_LEN = 8000


def provider_hrefs_from_html(html: str) -> list[str]:
    """Extract provider hrefs from Zocdoc index HTML."""
    if not html or not html.strip():
        logger.debug("provider_hrefs_from_html: empty html")
        return []
    soup = BeautifulSoup(html, "lxml")
    out: list[str] = []
    for anchor in soup.select('a[data-test="provider-link"]'):
        href = anchor.get("href")
        if href:
            out.append(str(href).strip())
    if not out and len(html) >= _SUBSTANTIVE_HTML_LEN:
        logger.warning(
            "provider_hrefs_from_html: no provider links (html_len=%d)",
            len(html),
        )
    return out


def profile_index_pagination_hrefs(html: str) -> list[str]:
    """Hrefs for numbered index pages (`data-test` like `2-page`), skipping disabled tabs."""
    if not html or not html.strip():
        logger.debug("profile_index_pagination_hrefs: empty html")
        return []
    soup = BeautifulSoup(html, "lxml")
    out: list[str] = []
    for anchor in soup.find_all("a", href=True):
        data_test = (anchor.get("data-test") or "").strip()
        if not _PAGE_LINK_TEST.match(data_test):
            continue
        if anchor.has_attr("disabled"):
            continue
        out.append(str(anchor["href"]).strip())
    return out


def absolute_zocdoc_urls(hrefs: list[str], *, origin: str = ZOCDOC_ORIGIN) -> list[str]:
    """Resolve hrefs to absolute zocdoc.com URLs and dedupe."""
    urls: list[str] = []
    for href in hrefs:
        href = (href or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        base = origin.rstrip("/")
        absolute = urljoin(base + "/", href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https") or "zocdoc.com" not in (parsed.netloc or "").lower():
            continue
        path = parsed.path or "/"
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")
        netloc = parsed.netloc.lower()
        urls.append(f"{parsed.scheme}://{netloc}{path}")
    urls = list(dict.fromkeys(urls))
    if hrefs and not urls:
        logger.warning(
            "absolute_zocdoc_urls: all %d hrefs dropped (origin=%s)",
            len(hrefs),
            origin,
        )
    return urls


def provider_slug_from_url(url: str) -> str | None:
    """Folder/file stem from a provider URL or path."""
    href = (url or "").strip()
    if not href:
        return None
    if href.startswith("/"):
        path = href
    else:
        path = urlparse(href).path or ""
    path = path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None
    return parts[-1]


def canonical_profile_index_url(url: str) -> str:
    """Canonicalize a profile index URL."""
    resolved = absolute_zocdoc_urls([url])
    return resolved[0] if resolved else url
