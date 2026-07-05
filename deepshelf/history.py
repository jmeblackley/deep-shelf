"""Build a taste profile from a reader's own history and ratings.

This is content-based personalisation: the books you loved reveal the subjects
to chase, the books you disliked reveal subjects to ease off, and everything
you've read is excluded from the results.  No account, no server — just a local
file you point at with ``--history``.

Two formats are understood automatically:

* **JSON** — ``[{"title": "...", "author": "...", "rating": 5}, ...]``
  (``author`` and ``rating`` optional; rating on a 1-5 scale).
* **CSV** — including a Goodreads library export (columns ``Title``, ``Author``,
  ``My Rating``); a generic ``title,author,rating`` header also works.

Ratings are interpreted around a neutral of ~3.5/5: above lifts a book's
subjects into the profile, below pushes them into ``avoid``.  A rating of 0
(Goodreads' "unrated") is treated as "read it, mild positive".
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .openlibrary import OpenLibraryClient
from .profile import TasteProfile

_NEUTRAL = 3.5
#: Cap on Open Library look-ups per run, so a 2,000-book export stays fast.
_MAX_LOOKUPS = 40


@dataclass
class HistoryEntry:
    title: str
    author: str = ""
    rating: Optional[float] = None  # 1..5, or None if unrated

    @property
    def informativeness(self) -> float:
        """How much this entry tells us — strong opinions (love/hate) rank
        above lukewarm or unrated ones, so the look-up budget is spent well."""
        if self.rating is None:
            return 0.0
        return abs(self.rating - _NEUTRAL)


def load_history(path) -> List[HistoryEntry]:
    path = Path(path)
    text = path.read_text("utf-8")
    if path.suffix.lower() == ".json":
        return _parse_json(text)
    return _parse_csv(text)


def _parse_json(text: str) -> List[HistoryEntry]:
    data = json.loads(text)
    out: List[HistoryEntry] = []
    for e in data:
        if isinstance(e, str):
            out.append(HistoryEntry(title=e))
        elif isinstance(e, dict) and e.get("title"):
            out.append(
                HistoryEntry(
                    title=str(e["title"]).strip(),
                    author=str(e.get("author", "")).strip(),
                    rating=_coerce_rating(e.get("rating")),
                )
            )
    return out


def _parse_csv(text: str) -> List[HistoryEntry]:
    reader = csv.DictReader(io.StringIO(text))
    # Map real headers to our fields, case-insensitively.  Handles both
    # Goodreads ("Title", "Author", "My Rating") and generic headers.
    field_map = {}
    for name in reader.fieldnames or []:
        low = name.strip().lower()
        if low in ("title", "book", "name"):
            field_map["title"] = name
        elif low in ("author", "authors"):
            field_map.setdefault("author", name)
        elif low in ("my rating", "rating", "your rating", "stars"):
            field_map["rating"] = name
    out: List[HistoryEntry] = []
    for row in reader:
        title = (row.get(field_map.get("title", ""), "") or "").strip()
        if not title:
            continue
        out.append(
            HistoryEntry(
                title=title,
                author=(row.get(field_map.get("author", ""), "") or "").strip(),
                rating=_coerce_rating(row.get(field_map.get("rating", ""))),
            )
        )
    return out


def _coerce_rating(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        r = float(value)
    except (TypeError, ValueError):
        return None
    # Goodreads uses 0 for "unrated".
    if r <= 0:
        return None
    return max(1.0, min(5.0, r))


def profile_from_history(
    entries: List[HistoryEntry],
    client: OpenLibraryClient,
    into: Optional[TasteProfile] = None,
    max_lookups: int = _MAX_LOOKUPS,
) -> TasteProfile:
    """Fold a reading history into a profile: chase loved subjects, ease off
    disliked ones, exclude everything already read."""
    profile = into or TasteProfile()

    # Every read title is excluded from recommendations, regardless of rating.
    for e in entries:
        profile.exclude.add(e.title)

    # Spend the look-up budget on the most opinionated entries first.
    ranked = sorted(entries, key=lambda e: e.informativeness, reverse=True)
    for e in ranked[:max_lookups]:
        subjects = _subjects_for(e, client)
        if not subjects:
            # Fall back to the title itself as a weak keyword signal.
            if e.rating is None or e.rating >= _NEUTRAL:
                profile.add_keyword(e.title)
            continue
        weight = _weight_for(e.rating)
        if weight >= 0:
            for s in subjects[:6]:
                profile.add_subject(s, weight=weight)
        else:
            for s in subjects[:6]:
                profile.add_avoid(s, weight=-weight)
    return profile


def _weight_for(rating: Optional[float]) -> float:
    """Map a rating to a subject weight.  Positive -> chase; negative -> avoid.

    5 -> +1.5, 4 -> +0.5, 3.5 (neutral/unrated) -> +0.3, 3 -> -0.1, 2 -> -1,
    1 -> -1.5.  Loved books pull hardest; merely-fine books barely register.
    """
    if rating is None:
        return 0.3
    return round(rating - _NEUTRAL, 3)


def _subjects_for(entry: HistoryEntry, client: OpenLibraryClient) -> List[str]:
    query = f"{entry.title} {entry.author}".strip()
    hits = client.search_keyword(query, limit=1)
    return hits[0].subjects if hits else []
