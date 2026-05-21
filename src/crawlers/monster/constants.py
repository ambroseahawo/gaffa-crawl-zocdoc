"""Monster job search constants."""

from __future__ import annotations

import os

from src.config.constants import DATA_DIR

MONSTER_ORIGIN = "https://www.monster.com"

JOBS_DATA_DIR = os.path.join(DATA_DIR, "monster")
JOBS_SEED_URL = (
    "https://www.monster.com/jobs/search?q=Software+Engineer&where=&page=1&so=m.h.lh"
)

MAX_LISTING_PAGES = 5
MIN_JOB_CARDS = 3
