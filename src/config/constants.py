"""application constants"""

from __future__ import annotations

CONCURRENT_REQUESTS = 5

DATA_DIR = "data"

TIME_LIMIT_MS = 60_000

DEFAULT_API_BASE = "https://api.gaffa.dev"
TERMINAL_STATES = frozenset({"completed", "failed"})

TOTAL_ATTEMPTS = 3
