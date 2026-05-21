"""Zocdoc site constants."""

from __future__ import annotations

import os

from src.config.constants import DATA_DIR

ZOCDOC_ORIGIN = "https://www.zocdoc.com"

# Max provider fetches per listing index page: 0 or None = unlimited.
MAX_PROVIDERS_PER_LISTING: int | None = 100

PROFILES_DATA_DIR = os.path.join(DATA_DIR, "zocdoc", "profiles")
PROFILES_SEED_URL = "https://www.zocdoc.com/profiles/new-york"
