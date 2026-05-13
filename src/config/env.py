"""Environment variables for the application."""

import os

from dotenv import load_dotenv

load_dotenv(override=True)

GAFFA_API_KEY = os.getenv("GAFFA_API_KEY")
GAFFA_CONCURRENT = os.getenv("GAFFA_CONCURRENT")
CONCURRENT_GAFFA_REQUESTS = os.getenv("CONCURRENT_GAFFA_REQUESTS")


def _env_truthy(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in ("1", "true", "yes", "on")


def gaffa_concurrency_settings() -> tuple[int, int]:
    """(index_batch_size, semaphore_slots)"""

    if not _env_truthy(GAFFA_CONCURRENT):
        return 1, 1
    raw = (CONCURRENT_GAFFA_REQUESTS or "").strip()
    if not raw:
        return 5, 5
    try:
        n = int(raw)
    except ValueError:
        return 5, 5
    if n < 1:
        return 5, 5
    return n, n
