"""application constants"""

from __future__ import annotations

ZOCDOC_ORIGIN = "https://www.zocdoc.com"

TIME_LIMIT_MS = 60_000
CONCURRENT_REQUESTS = 5

DATA_DIR = "data"

DEFAULT_API_BASE = "https://api.gaffa.dev"
TERMINAL_STATES = frozenset({"completed", "failed"})

# Max provider fetches per listing index page; budget resets each page. ``0``/``None`` = unlimited.
MAX_PROVIDERS_PER_LISTING: int | None = 100
