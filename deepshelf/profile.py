"""The taste profile: the distilled result of probing a reader.

A :class:`TasteProfile` is deliberately abstract.  It does not store "genres you
like" so much as *pressures* to apply while searching the deep shelves:

* ``subjects`` / ``keywords`` — where to look.
* ``popularity_lean`` — the reader's stated tilt toward the well-known or the
  little-known.  **Neutral by default**: popularity is always *considered*, but
  it never counts against a book unless the reader asks it to.
* ``era_bias`` — tilt toward the old (negative) or the new (positive).  Also
  neutral by default.
* ``adventurousness`` — how much serendipitous noise to inject.

The interview produces one of these; the recommender consumes it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class TasteProfile:
    """A weighted description of what to go hunting for, and how."""

    #: Open Library subject tags -> weight.  Higher weight = queried harder.
    subjects: Counter = field(default_factory=Counter)
    #: Subjects the reader has signalled *away* from (learned from books they
    #: rated poorly).  Applied as a gentle, personal penalty — this is learned
    #: from the reader's own taste, not a blanket bias.
    avoid: Counter = field(default_factory=Counter)
    #: Free-text search phrases pulled from the reader's own words.
    keywords: List[str] = field(default_factory=list)
    #: Short mood words, used only to colour the explanation.
    moods: List[str] = field(default_factory=list)

    #: -1..1 — how the reader *leans* on popularity.  0 = neutral: popularity is
    #: considered and shown, but does not move the ranking.  Negative leans
    #: toward the little-known, positive toward the well-loved.  It is a
    #: preference, never a penalty.
    popularity_lean: float = 0.0
    #: -1..1 — negative leans old, positive leans contemporary.  0 = neutral:
    #: recency is considered but does not move the ranking.
    era_bias: float = 0.0
    #: 0..1 — how much serendipity (relevant-but-unexpected picks) to seek.
    #: Following the literature, serendipity is *relevance x unexpectedness*, so
    #: this dial never buys irrelevant noise — only lateral, surprising fits.
    adventurousness: float = 0.4

    #: The reader's primary "doorway" into a book, after Nancy Pearl's readers'
    #: advisory framework: one of "character", "setting", "language", "story",
    #: or "" (unspecified).  Shapes both search and explanation.
    doorway: str = ""
    #: A one-word emotional register the reader is after (a Saricks "tone"
    #: appeal factor), e.g. "bleak", "hopeful", "playful"; "" if unspecified.
    tone: str = ""

    #: Semantic tokens for each option the reader chose (e.g. "cave", "rumor").
    #: The synthesis layer reads *combinations* of these to infer nuance.
    signals: set = field(default_factory=set)
    #: Human-readable labels for emergent threads the synthesis layer inferred
    #: from combinations of answers (shown back to the reader for transparency).
    emergent: List[str] = field(default_factory=list)

    #: Work keys or normalised titles the reader has already read.
    exclude: set = field(default_factory=set)
    #: Preferred languages (ISO codes); empty means "no preference".
    languages: List[str] = field(default_factory=list)

    def add_subject(self, subject: str, weight: float = 1.0) -> None:
        subject = subject.strip().lower()
        if subject:
            self.subjects[subject] += weight

    def add_keyword(self, phrase: str) -> None:
        phrase = phrase.strip()
        if phrase and phrase not in self.keywords:
            self.keywords.append(phrase)

    def add_avoid(self, subject: str, weight: float = 1.0) -> None:
        subject = subject.strip().lower()
        if subject:
            self.avoid[subject] += weight

    def top_subjects(self, n: int = 6) -> List[str]:
        return [s for s, _ in self.subjects.most_common(n)]

    def blend(self, tune: Dict[str, float]) -> None:
        """Nudge the continuous dials.  Values are *deltas*, then clamped."""
        if "popularity_lean" in tune:
            self.popularity_lean = _clamp(
                self.popularity_lean + tune["popularity_lean"], -1.0, 1.0
            )
        if "era_bias" in tune:
            self.era_bias = _clamp(self.era_bias + tune["era_bias"], -1.0, 1.0)
        if "adventurousness" in tune:
            self.adventurousness = _clamp(
                self.adventurousness + tune["adventurousness"], 0.0, 1.0
            )

    def summary(self) -> str:
        era = (
            "leaning older"
            if self.era_bias < -0.15
            else "leaning newer"
            if self.era_bias > 0.15
            else "any era"
        )
        pop = (
            "toward the little-known"
            if self.popularity_lean < -0.15
            else "toward the well-loved"
            if self.popularity_lean > 0.15
            else "popularity neutral"
        )
        subs = ", ".join(self.top_subjects(5)) or "wide open"
        def _article(word: str) -> str:
            return "an" if word[:1].lower() in "aeiou" else "a"

        appeal = ""
        if self.doorway:
            appeal = f"You read for {self.doorway}"
            if self.tone:
                appeal += f", in {_article(self.tone)} {self.tone} register"
            appeal += ". "
        elif self.tone:
            appeal = f"{_article(self.tone).capitalize()} {self.tone} register. "
        return (
            f"{appeal}{era}; {pop}; serendipity {self.adventurousness:.0%}. "
            f"Threads: {subs}."
        )


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))
