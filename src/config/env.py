"""Environment variables for the application."""

import os

from dotenv import load_dotenv

from .constants import CONCURRENT_REQUESTS

load_dotenv(override=True)

GAFFA_API_KEY = os.getenv("GAFFA_API_KEY")
GAFFA_CONCURRENT = os.getenv("GAFFA_CONCURRENT")
CONCURRENT_GAFFA_REQUESTS = os.getenv("CONCURRENT_GAFFA_REQUESTS", str(CONCURRENT_REQUESTS))


def gaffa_concurrency_settings() -> tuple[int, int]:
    """(index_batch_size, semaphore_slots)"""
    if not GAFFA_CONCURRENT or GAFFA_CONCURRENT.strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return 1, 1
    raw = (CONCURRENT_GAFFA_REQUESTS or "").strip()
    if not raw:
        return CONCURRENT_REQUESTS, CONCURRENT_REQUESTS
    try:
        n = int(raw)
    except ValueError:
        return CONCURRENT_REQUESTS, CONCURRENT_REQUESTS
    if n < 1:
        return CONCURRENT_REQUESTS, CONCURRENT_REQUESTS
    return n, n
