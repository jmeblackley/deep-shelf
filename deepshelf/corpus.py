"""Loader for the hand-curated deep-cuts corpus (``data/deep_cuts.json``).

The corpus does two jobs: it guarantees Deepshelf gives excellent answers even
with no network, and it seeds the live results with human judgement the API
cannot supply.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import List

from .openlibrary import Book

_DATA = Path(__file__).parent / "data" / "deep_cuts.json"


@lru_cache(maxsize=1)
def load_corpus() -> List[Book]:
    raw = json.loads(_DATA.read_text("utf-8"))
    books: List[Book] = []
    for entry in raw.get("books", []):
        books.append(
            Book(
                key="curated:" + _slug(entry["title"]),
                title=entry["title"],
                authors=entry.get("authors", []),
                year=entry.get("year"),
                edition_count=entry.get("edition_count", 0),
                ratings_count=entry.get("ratings_count", 0),
                ratings_average=entry.get("ratings_average"),
                readinglog_count=entry.get("ratings_count", 0),
                subjects=[s.lower() for s in entry.get("subjects", [])],
                found_via=["curated"],
                curated=True,
                note=entry.get("note"),
            )
        )
    return books


def _slug(title: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in title).strip("-")
