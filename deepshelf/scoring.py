"""The scoring engine.

Every book is described by a handful of signals, each normalised to roughly
0..1.  Two of those signals — **popularity** and **recency** — are always
*computed and shown*, so they are genuinely part of how a recommendation is
formed.  But they are treated as neutral information, not as strikes against a
book:

    score =  w_match   * thematic_match          (does it hit the reader's threads?)
           + w_quality * quality_signal          (is it actually good, if we can tell?)
           + w_free    * readable_free            (bonus: full text on the Archive)
           + lean_pop  * popularity              (reader's tilt; 0 = no effect)
           + era_bias  * recency                 (reader's tilt; 0 = no effect)
           + w_serend  * serendipity              (a little deterministic chaos)

When the reader states no preference (the default), ``lean_pop`` and
``era_bias`` are 0, so popularity and recency move the ranking *not at all* —
they are considered, surfaced, and used to give the shelf a considered spread,
but nothing is penalised.  A reader who wants to lean toward the obscure or the
old sets a negative lean; one who wants the beloved or the brand-new sets a
positive one.

Nothing here is random in the non-reproducible sense: the "serendipity" jitter
is a hash of the title, so runs are stable.
"""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass
from typing import List, Optional

from .openlibrary import Book
from .profile import TasteProfile

# A book needs at least this many ratings before we trust its average at all.
_MIN_RATINGS_FOR_QUALITY = 8


@dataclass
class Scored:
    book: Book
    score: float
    match: float
    popularity: float
    recency: float
    quality: float
    serendipity: float
    reasons: List[str]
    #: Flagged when this pick is carried mainly by serendipity (a relevant but
    #: unexpected, lateral fit) rather than by direct thematic match.
    wildcard: bool = False


def _log_norm(count: int, ceiling: float) -> float:
    """Map a count onto 0..1 via log scaling. ``ceiling`` is the count that
    saturates to ~1.0."""
    if count <= 0:
        return 0.0
    return min(1.0, math.log1p(count) / math.log1p(ceiling))


def popularity_signal(book: Book) -> float:
    """0 = few have heard of it; 1 = it is on every airport shelf.

    A neutral descriptor.  Blends three independent signals so no single metric
    dominates: edition sprawl, rating volume, and reading-log volume.
    """
    editions = _log_norm(book.edition_count, ceiling=120)  # 120+ editions ~ canon
    ratings = _log_norm(book.ratings_count, ceiling=3000)
    logged = _log_norm(book.readinglog_count, ceiling=8000)
    return 0.4 * editions + 0.3 * ratings + 0.3 * logged


def recency_signal(book: Book, floor_year: int = 1500, now_year: int = 2025) -> float:
    """0 = ancient, 1 = published this year.  A neutral descriptor.  Unknown
    year is treated as mid-old (0.3), since the deep shelves are full of undated
    things but we don't want to guess too hard."""
    if not book.year:
        return 0.3
    year = max(floor_year, min(now_year, book.year))
    return (year - floor_year) / (now_year - floor_year)


def quality_signal(book: Book) -> Optional[float]:
    """0..1 from the rating average, but only when there are enough ratings to
    mean anything.  Returns ``None`` when we simply cannot tell — and 'we cannot
    tell' is deliberately *not* punished, so unrated gems survive."""
    if book.ratings_average is None or book.ratings_count < _MIN_RATINGS_FOR_QUALITY:
        return None
    return max(0.0, min(1.0, book.ratings_average / 5.0))


def thematic_match(book: Book, profile: TasteProfile) -> float:
    """How many of the reader's threads run through this book.

    Two contributions: overlap between the book's own subject tags and the
    profile's subjects, plus a small credit for how many distinct queries
    surfaced it (a book found via three different threads is a strong signal).
    """
    if not profile.subjects:
        base = 0.4
    else:
        wanted = set(profile.subjects)
        book_subjects = set(book.subjects)
        # Substring-aware overlap: "ghost stories" should match "ghost".
        hits = 0.0
        for want in wanted:
            weight = profile.subjects[want]
            if any(want in bs or bs in want for bs in book_subjects):
                hits += weight
        total_weight = sum(profile.subjects.values()) or 1.0
        base = hits / total_weight
    provenance = max(0.0, min(1.0, (len(set(book.found_via)) - 1) * 0.25))
    return max(0.0, min(1.0, 0.75 * base + 0.25 * provenance))


def unexpectedness(book: Book, profile: TasteProfile) -> float:
    """How *surprising* a relevant book is: 1.0 when it connects to the reader
    through a secondary thread rather than the one or two obvious ones, 0.0 when
    it is the on-the-nose hit they'd predict themselves.

    This follows the recommender-systems literature, where serendipity is
    unexpectedness *combined with* relevance — not mere novelty or obscurity
    (Kaminskas & Bridge 2016, ACM TiiS; Ziarani & Ravanmehr 2021, JCST).
    """
    if not profile.subjects:
        return 0.0
    obvious = profile.top_subjects(2)
    book_subjects = set(book.subjects)
    hits_obvious = any(
        t in bs or bs in t for t in obvious for bs in book_subjects
    )
    return 0.0 if hits_obvious else 1.0


def avoidance(book: Book, profile: TasteProfile) -> float:
    """0..1 — how strongly a book leans on themes the reader has personally
    rated poorly.  Learned from the reader's own history, so unlike a popularity
    bias this is a legitimate, individual signal."""
    if not profile.avoid:
        return 0.0
    book_subjects = set(book.subjects)
    hits = 0.0
    for sub, w in profile.avoid.items():
        if any(sub in bs or bs in sub for bs in book_subjects):
            hits += w
    total = sum(profile.avoid.values()) or 1.0
    return min(1.0, hits / total)


def _jitter(book: Book, strength: float) -> float:
    """A whisper of deterministic tie-breaking variety, keyed on the title so a
    given book always jitters the same way within a session.  Small on purpose:
    variety must never override relevance."""
    if strength <= 0:
        return 0.0
    seed = zlib.crc32(book.title.encode("utf-8")) / 0xFFFFFFFF  # 0..1
    return (seed - 0.5) * 2 * strength


def score_book(book: Book, profile: TasteProfile) -> Scored:
    match = thematic_match(book, profile)
    pop = popularity_signal(book)
    rec = recency_signal(book)
    qual = quality_signal(book)

    # Popularity and recency enter the score ONLY through the reader's stated
    # lean.  At the neutral default (lean = 0) both terms vanish, so nothing is
    # penalised — the signals are considered and displayed, not held against the
    # book.  We centre each signal on 0.5 so a lean tilts symmetrically: a
    # positive popularity lean rewards the well-known and gently discounts the
    # obscure, and vice-versa, without ever dominating thematic fit.
    pop_term = profile.popularity_lean * (pop - 0.5)
    rec_term = profile.era_bias * (rec - 0.5)

    # Quality helps, but only in proportion to relevance — a five-star book that
    # has nothing to do with the reader should not ride its rating to the top
    # (the failure mode a pure-accuracy score produces).
    quality_term = (0.5 * qual * (0.35 + 0.65 * match)) if qual is not None else 0.0
    free_term = 0.1 if book.read_free_url else 0.0

    # Serendipity = relevance x unexpectedness, scaled by the reader's appetite.
    # Because it is multiplied by `match`, it can never lift an irrelevant book;
    # it only rewards lateral, surprising fits — the "spark".
    unexp = unexpectedness(book, profile)
    serendipity = profile.adventurousness * max(0.0, match) * unexp
    jitter = _jitter(book, profile.adventurousness * 0.03)

    # A gentle, personal penalty for themes the reader has rated poorly.
    avoid_term = -0.5 * avoidance(book, profile)

    score = (
        1.2 * match
        + quality_term
        + free_term
        + pop_term
        + rec_term
        + serendipity
        + avoid_term
        + jitter
    )

    # A pick is a "wildcard" when serendipity is what carries it: genuinely
    # relevant, but reached through an unexpected thread.
    wildcard = unexp >= 1.0 and serendipity >= 0.12 and match < 0.5

    reasons = _explain(book, match, pop, rec, qual, unexp, profile)
    return Scored(
        book=book,
        score=score,
        match=match,
        popularity=pop,
        recency=rec,
        quality=qual if qual is not None else -1.0,
        serendipity=serendipity,
        reasons=reasons,
        wildcard=wildcard,
    )


def _explain(book, match, pop, rec, qual, unexp, profile) -> List[str]:
    reasons: List[str] = []

    # Lead with the serendipity story when it applies — an unexpected fit needs
    # an explanation to land as delight rather than confusion (Kaminskas &
    # Bridge 2016).
    if unexp >= 1.0 and match > 0 and profile.adventurousness > 0:
        shared = _shared_threads(book, profile)
        if shared:
            reasons.append("a lateral fit — reached via " + shared[0])

    # Always narrate the popularity/recency reading — they were considered.
    if pop < 0.2:
        reasons.append("little-known")
    elif pop < 0.5:
        reasons.append("known but not ubiquitous")
    elif pop > 0.8:
        reasons.append("widely beloved")
    if book.year:
        if book.year < 1970:
            reasons.append(f"from {book.year}")
        elif book.year >= 2015:
            reasons.append(f"recent ({book.year})")

    if book.read_free_url:
        reasons.append("full text free on the Internet Archive")
    if qual is not None and qual >= 0.8:
        reasons.append("well-rated by those who found it")
    if match >= 0.5:
        shared = _shared_threads(book, profile)
        if shared:
            reasons.append("threads: " + ", ".join(shared[:3]))
    if len(set(book.found_via)) >= 2:
        reasons.append("surfaced along several of your threads at once")
    if not reasons:
        reasons.append("an outside pick to widen the aperture")
    return reasons


def _shared_threads(book: Book, profile: TasteProfile) -> List[str]:
    out = []
    book_subjects = set(book.subjects)
    for want in profile.top_subjects(12):
        if any(want in bs or bs in want for bs in book_subjects):
            out.append(want)
    return out


def rank(books: List[Book], profile: TasteProfile) -> List[Scored]:
    """Score, then sort high-to-low."""
    scored = [score_book(b, profile) for b in books]
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored
