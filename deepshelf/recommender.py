"""Orchestration: turn a :class:`TasteProfile` into a ranked list of books.

The pipeline:

1. Gather candidates from the live Open Library catalogue (one query per top
   subject, plus the reader's own keywords) and from the curated corpus.
2. Merge duplicates, preferring live metadata but keeping curator notes.
3. Filter out anything the reader has already read.
4. Score every candidate with the obscurity engine and sort.
5. Optionally diversify so one author can't dominate the shelf.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from .corpus import load_corpus
from .openlibrary import Book, OpenLibraryClient
from .profile import TasteProfile
from .scoring import Scored, rank


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def _merge(into: Book, other: Book) -> None:
    """Fold ``other`` into ``into`` (``into`` wins on live data)."""
    into.found_via = list(dict.fromkeys(into.found_via + other.found_via))
    if not into.subjects:
        into.subjects = other.subjects
    if into.note is None and other.note:
        into.note = other.note
    into.curated = into.curated or other.curated


def gather_candidates(
    profile: TasteProfile,
    client: OpenLibraryClient,
    per_subject: int = 30,
    max_subjects: int = 6,
) -> List[Book]:
    pool: Dict[str, Book] = {}

    def absorb(books: List[Book]) -> None:
        for b in books:
            nk = _norm_title(b.title) + "|" + _norm_title(b.author_line)
            if nk in pool:
                _merge(pool[nk], b)
            else:
                pool[nk] = b

    # Curated first, so live data merges *onto* curated (live wins, note kept).
    absorb(load_corpus())

    for subject in profile.top_subjects(max_subjects):
        absorb(client.search_subject(subject, limit=per_subject))
    for phrase in profile.keywords[:5]:
        absorb(client.search_keyword(phrase, limit=20))

    return list(pool.values())


def _excluded(book: Book, profile: TasteProfile) -> bool:
    if book.key in profile.exclude:
        return True
    nt = _norm_title(book.title)
    return any(nt == _norm_title(x) for x in profile.exclude)


def _has_footprint(book: Book) -> bool:
    """A light 'known-enough' test: the book has *some* trace in the world —
    more than one edition, a rating, a scan, or a curator's vouch.  Filters out
    phantom single-record catalogue entries without touching genuine deep cuts
    (which almost always clear at least one of these)."""
    return (
        book.curated
        or book.edition_count >= 2
        or book.ratings_count >= 1
        or book.readinglog_count >= 1
        or book.public_scan
        or bool(book.ia_ids)
    )


#: A candidate must clear this thematic-match floor to be recommendable, so a
#: highly-rated but irrelevant book cannot ride its rating onto the shelf.  The
#: floor is relaxed automatically when it would starve the results.
_RELEVANCE_FLOOR = 0.06


def _apply_relevance_floor(ranked: List[Scored], profile, limit: int) -> List[Scored]:
    """Drop candidates that don't actually connect to the reader's threads.

    Serendipity in the literature is relevance *and* unexpectedness; this guard
    enforces the relevance half so 'adventurous' never collapses into noise.
    Wildcards (relevant-but-lateral) clear the floor because they still match.
    """
    if not profile.subjects:
        return ranked
    relevant = [s for s in ranked if s.match >= _RELEVANCE_FLOOR]
    # Only enforce the floor if enough relevant candidates remain to fill the
    # shelf; otherwise fall back to the full ranking rather than return nothing.
    if len(relevant) >= max(limit, 5):
        return relevant
    return ranked


def _apply_known_floor(ranked: List[Scored], limit: int) -> List[Scored]:
    """Drop zero-footprint phantom records, with a fallback so a thin pool is
    never emptied."""
    known = [s for s in ranked if _has_footprint(s.book)]
    if len(known) >= max(limit, 5):
        return known
    return ranked


def _promote_wildcard(out: List[Scored], pool: List[Scored], profile) -> None:
    """Guarantee at least one relevant-but-unexpected pick when the reader is
    adventurous — the deliberate explore/exploit spark (Kaminskas & Bridge
    2016).  Swaps the weakest non-wildcard for the strongest available wildcard."""
    if profile.adventurousness < 0.35 or len(out) < 3:
        return
    if any(s.wildcard for s in out):
        return
    chosen = {id(s) for s in out}
    wildcards = [s for s in pool if s.wildcard and id(s) not in chosen]
    if not wildcards:
        return
    non_wild = [s for s in out if not s.wildcard]
    if not non_wild:
        return
    weakest = min(non_wild, key=lambda s: s.score)
    out[out.index(weakest)] = wildcards[0]


def recommend(
    profile: TasteProfile,
    client: Optional[OpenLibraryClient] = None,
    limit: int = 8,
    diversify: bool = True,
) -> List[Scored]:
    client = client or OpenLibraryClient()
    candidates = [
        b for b in gather_candidates(profile, client) if not _excluded(b, profile)
    ]
    ranked = _apply_relevance_floor(rank(candidates, profile), profile, limit)
    ranked = _apply_known_floor(ranked, limit)

    if not diversify:
        out = ranked[:limit]
        _promote_wildcard(out, ranked, profile)
        return out

    # Diversify: allow at most two books per author until we run low.
    out: List[Scored] = []
    seen_authors: Dict[str, int] = {}
    overflow: List[Scored] = []
    for s in ranked:
        author = s.book.author_line.lower()
        if seen_authors.get(author, 0) >= 2:
            overflow.append(s)
            continue
        seen_authors[author] = seen_authors.get(author, 0) + 1
        out.append(s)
        if len(out) >= limit:
            break
    if len(out) < limit:
        out.extend(overflow[: limit - len(out)])
    out = out[:limit]
    _promote_wildcard(out, ranked, profile)
    return out
