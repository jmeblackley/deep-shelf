"""Tests for Deepshelf.

These run fully offline: no test touches the network.  The scoring and
recommendation logic is exercised against the curated corpus and synthetic
books, so the core promise — weighing against popularity and recency — is
actually asserted, not just hoped for.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deepshelf.corpus import load_corpus
from deepshelf.interview import QUESTIONS, quick_profile
from deepshelf.openlibrary import Book, OpenLibraryClient
from deepshelf.profile import TasteProfile
from deepshelf.recommender import recommend
from deepshelf import scoring


# --- scoring: the core promise ---------------------------------------------

def _book(title, **kw):
    return Book(key="k:" + title, title=title, **kw)


def _pair(subjects, avg=4.2):
    """Two books identical except for popularity — used to isolate the lean."""
    obscure = _book("Quiet Gem", year=1958, subjects=subjects,
                    edition_count=3, ratings_count=12, ratings_average=avg,
                    readinglog_count=12)
    popular = _book("Airport Bestseller", year=1958, subjects=subjects,
                    edition_count=400, ratings_count=80000, ratings_average=avg,
                    readinglog_count=60000)
    obscure.found_via = ["subject:essays"]
    popular.found_via = ["subject:essays"]
    return obscure, popular


def test_popularity_signal_monotonic():
    obscure = _book("obscure", edition_count=2, ratings_count=3, readinglog_count=1)
    famous = _book("famous", edition_count=300, ratings_count=90000,
                   readinglog_count=50000)
    assert scoring.popularity_signal(obscure) < scoring.popularity_signal(famous)
    assert scoring.popularity_signal(famous) > 0.8


def test_recency_signal_orders_by_year():
    old = _book("old", year=1602)
    mid = _book("mid", year=1950)
    new = _book("new", year=2024)
    assert scoring.recency_signal(old) < scoring.recency_signal(mid)
    assert scoring.recency_signal(mid) < scoring.recency_signal(new)


def test_neutral_lean_does_not_penalise_popularity():
    """The core promise: at the default neutral lean, an identical popular and
    obscure book score *equally* — popularity is considered, not held against."""
    # adventurousness=0 removes the title-keyed serendipity jitter so we can
    # isolate the popularity term; leans are the thing under test here.
    profile = TasteProfile(adventurousness=0.0)  # popularity_lean/era_bias == 0
    profile.add_subject("essays")
    profile.add_subject("memory")
    obscure, popular = _pair(["essays", "memory"])
    s_obscure = scoring.score_book(obscure, profile)
    s_popular = scoring.score_book(popular, profile)
    # Same theme, same quality, same era — popularity must not move the score.
    assert s_obscure.score == pytest.approx(s_popular.score, abs=1e-9)


def test_lean_obscure_prefers_little_known():
    profile = TasteProfile(popularity_lean=-0.8, adventurousness=0.0)
    profile.add_subject("essays")
    profile.add_subject("memory")
    obscure, popular = _pair(["essays", "memory"])
    ranked = scoring.rank([popular, obscure], profile)
    assert ranked[0].book.title == "Quiet Gem"


def test_lean_popular_prefers_well_known():
    profile = TasteProfile(popularity_lean=0.8, adventurousness=0.0)
    profile.add_subject("essays")
    profile.add_subject("memory")
    obscure, popular = _pair(["essays", "memory"])
    ranked = scoring.rank([obscure, popular], profile)
    assert ranked[0].book.title == "Airport Bestseller"


def test_neutral_era_does_not_penalise_recency():
    profile = TasteProfile(adventurousness=0.0)  # era_bias == 0.0
    profile.add_subject("essays")
    old = _book("From 1930", year=1930, subjects=["essays"], edition_count=10,
                ratings_count=50, ratings_average=4.0, readinglog_count=50)
    new = _book("From 2024", year=2024, subjects=["essays"], edition_count=10,
                ratings_count=50, ratings_average=4.0, readinglog_count=50)
    assert scoring.score_book(old, profile).score == pytest.approx(
        scoring.score_book(new, profile).score, abs=1e-9)


def test_era_lean_old_prefers_older():
    profile = TasteProfile(era_bias=-0.8, adventurousness=0.0)
    subjects = ["essays"]
    old = _book("From 1930", year=1930, subjects=subjects, edition_count=10,
                ratings_count=50, ratings_average=4.0)
    new = _book("From 2024", year=2024, subjects=subjects, edition_count=10,
                ratings_count=50, ratings_average=4.0)
    profile.add_subject("essays")
    ranked = scoring.rank([new, old], profile)
    assert ranked[0].book.title == "From 1930"


def test_era_lean_new_flips_preference():
    profile = TasteProfile(era_bias=0.8)
    subjects = ["essays"]
    old = _book("From 1930", year=1930, subjects=subjects, edition_count=10,
                ratings_count=50, ratings_average=4.0)
    new = _book("From 2024", year=2024, subjects=subjects, edition_count=10,
                ratings_count=50, ratings_average=4.0)
    profile.add_subject("essays")
    ranked = scoring.rank([old, new], profile)
    assert ranked[0].book.title == "From 2024"


def test_quality_needs_enough_ratings():
    assert scoring.quality_signal(_book("x", ratings_average=5.0, ratings_count=2)) is None
    assert scoring.quality_signal(_book("x", ratings_average=4.0, ratings_count=50)) == pytest.approx(0.8)


def test_jitter_is_deterministic():
    b = _book("Stable Title")
    assert scoring._jitter(b, 0.5) == scoring._jitter(b, 0.5)
    assert scoring._jitter(b, 0.0) == 0.0


def test_serendipity_requires_relevance():
    """The core literature finding: serendipity is relevance x unexpectedness,
    so an unexpected but *irrelevant* book earns zero serendipity."""
    profile = TasteProfile(adventurousness=1.0)
    profile.add_subject("cybernetics", weight=3)  # top thread
    profile.add_subject("systems", weight=2)      # second thread
    profile.add_subject("information theory", weight=1)  # a secondary thread
    # Lateral-but-relevant: matches only the secondary thread, not the top two.
    lateral = _book("Lateral", subjects=["information theory"])
    # Irrelevant: shares nothing with the reader's threads.
    noise = _book("Noise", subjects=["romance", "cooking"])
    assert scoring.score_book(lateral, profile).serendipity > 0
    assert scoring.score_book(noise, profile).serendipity == 0.0


def test_unexpectedness_zero_for_obvious_hit():
    profile = TasteProfile()
    profile.add_subject("cybernetics", weight=5)  # the obvious top thread
    obvious = _book("Obvious", subjects=["cybernetics"])
    assert scoring.unexpectedness(obvious, profile) == 0.0


def test_thematic_match_substring_aware():
    profile = TasteProfile()
    profile.add_subject("ghost")
    b = _book("Haunted", subjects=["ghost stories", "the gothic"])
    assert scoring.thematic_match(b, profile) > 0.3


# --- interview / profile ----------------------------------------------------

def test_quick_profile_maps_options_to_subjects():
    profile = quick_profile({"doorway": "1"})  # "library quietly on fire"
    assert "philosophy" in profile.subjects
    assert profile.subjects["philosophy"] > 0


def test_synthesis_produces_emergent_thread_from_combo():
    # cave + deep -> "an obsessive descent into a single subject"
    profile = quick_profile({"doorway": "2", "hunger": "1"})
    assert profile.emergent, "combo should have fired"
    assert any("descent" in e for e in profile.emergent)
    assert "speleology" in profile.subjects
    # Emergent subjects are weighted above raw answers.
    assert profile.subjects["speleology"] > profile.subjects.get("caves", 0)


def test_synthesis_is_emergent_not_additive():
    # Neither answer alone yields the emergent thread; only their combination.
    only_cave = quick_profile({"doorway": "2"})
    only_deep = quick_profile({"hunger": "1"})
    both = quick_profile({"doorway": "2", "hunger": "1"})
    assert not only_cave.emergent
    assert not only_deep.emergent
    assert both.emergent
    assert "speleology" not in only_cave.subjects
    assert "speleology" not in only_deep.subjects


def test_freeform_obsession_becomes_search_fuel():
    profile = quick_profile({"obsession": "lighthouses, grief"})
    assert "lighthouses" in profile.keywords
    assert "grief" in profile.keywords


def test_option_tune_moves_dials():
    base = TasteProfile().popularity_lean  # 0.0
    # trust=2 (rumor) leans toward the overlooked: popularity_lean -0.2
    profile = quick_profile({"trust": "2"})
    assert profile.popularity_lean < base
    # familiarity=3 leans the other way, toward the well-loved.
    profile2 = quick_profile({"familiarity": "3"})
    assert profile2.popularity_lean > base


def test_familiarity_neutral_option_stays_neutral():
    profile = quick_profile({"familiarity": "2"})  # "surprise me"
    assert profile.popularity_lean == 0.0


def test_every_question_option_records_a_choice():
    # Some options are intentionally neutral on subjects (e.g. "surprise me"),
    # but every option must register *some* effect: a subject, a keyword, a mood,
    # or a dial nudge.
    for q in QUESTIONS:
        if q.freeform is not None:
            continue
        for i in range(len(q.options)):
            p = quick_profile({q.key: str(i + 1)})
            touched = bool(p.subjects or p.keywords or p.moods)
            assert touched, f"{q.key} option {i+1} recorded nothing"


def test_profile_clamps_dials():
    p = TasteProfile(popularity_lean=0.95)
    p.blend({"popularity_lean": 0.5})
    assert p.popularity_lean == 1.0
    p.blend({"era_bias": -5})
    assert p.era_bias == -1.0


# --- corpus -----------------------------------------------------------------

def test_corpus_loads_and_is_deep():
    corpus = load_corpus()
    assert len(corpus) >= 30
    for b in corpus:
        assert b.curated
        assert b.note
        assert b.subjects
        # Curated deep cuts should not be runaway bestsellers.
        assert scoring.popularity_signal(b) < 0.8


# --- recommender (offline end-to-end) --------------------------------------

def _offline_client():
    return OpenLibraryClient(offline=True)


def test_recommend_offline_returns_picks():
    profile = quick_profile({"texture": "4", "obsession": "landscape, ecology"})
    results = recommend(profile, client=_offline_client(), limit=5)
    assert 1 <= len(results) <= 5
    # Results are sorted descending by score.
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_recommend_excludes_read_titles():
    profile = TasteProfile()
    profile.add_subject("nature writing")
    profile.exclude.add("The Peregrine")
    results = recommend(profile, client=_offline_client(), limit=20)
    assert all(r.book.title != "The Peregrine" for r in results)


def test_recommend_diversifies_authors():
    profile = TasteProfile(popularity_lean=-0.4)
    for s in ["essays", "modernism", "nature writing", "philosophy"]:
        profile.add_subject(s)
    results = recommend(profile, client=_offline_client(), limit=8, diversify=True)
    authors = [r.book.author_line for r in results]
    for a in set(authors):
        assert authors.count(a) <= 2


def test_offline_client_makes_no_network_call():
    client = _offline_client()
    assert client.search_subject("anything") == []
    assert client.search_keyword("anything") == []


class _FakeClient:
    """A client that injects a highly-rated but irrelevant 'noise' book plus a
    genuinely on-theme one, to test the relevance floor."""

    def __init__(self):
        self.noise = Book(
            key="/works/NOISE", title="Popular Irrelevance",
            authors=["Nobody"], year=2024, edition_count=5, ratings_count=500,
            ratings_average=4.9, readinglog_count=500,
            subjects=["romance", "cooking"], found_via=["subject:cybernetics"],
        )
        self.hit = Book(
            key="/works/HIT", title="On Systems", authors=["Someone"], year=1968,
            edition_count=4, ratings_count=30, ratings_average=4.0,
            readinglog_count=30, subjects=["cybernetics", "systems"],
            found_via=["subject:cybernetics"],
        )

    def search_subject(self, subject, limit=40):
        if "cybernetic" in subject or "system" in subject:
            return [self.noise, self.hit]
        return []

    def search_keyword(self, phrase, limit=25):
        return []


def test_relevance_floor_filters_high_rated_noise():
    profile = TasteProfile()
    for s in ["cybernetics", "systems", "information theory", "philosophy",
              "science", "mathematics"]:
        profile.add_subject(s)
    results = recommend(profile, client=_FakeClient(), limit=8)
    titles = [r.book.title for r in results]
    # The 4.9-star romance/cooking book must not ride its rating onto the shelf.
    assert "Popular Irrelevance" not in titles
    assert "On Systems" in titles


def test_doorway_and_tone_recorded_on_profile():
    profile = quick_profile({"doorway_appeal": "3", "tone": "1"})
    assert profile.doorway == "language"
    assert profile.tone == "bleak"
    assert "prose style" in profile.subjects


# --- history / ratings-based personalisation --------------------------------

import tempfile  # noqa: E402

from deepshelf.history import (  # noqa: E402
    HistoryEntry, _coerce_rating, load_history, profile_from_history,
)


def _write(text, suffix):
    f = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8")
    f.write(text)
    f.close()
    return f.name


def test_load_history_json():
    path = _write(
        '[{"title": "Solaris", "author": "Lem", "rating": 5}, {"title": "X"}]',
        ".json",
    )
    entries = load_history(path)
    assert entries[0].title == "Solaris" and entries[0].rating == 5.0
    assert entries[1].rating is None


def test_load_history_goodreads_csv():
    csv_text = "Title,Author,My Rating\nDune,Herbert,2\nStoner,Williams,5\n"
    path = _write(csv_text, ".csv")
    entries = load_history(path)
    by_title = {e.title: e for e in entries}
    assert by_title["Dune"].rating == 2.0
    assert by_title["Stoner"].author == "Williams"


def test_coerce_rating_treats_zero_as_unrated():
    assert _coerce_rating("0") is None      # Goodreads "unrated"
    assert _coerce_rating("4") == 4.0
    assert _coerce_rating("") is None


class _SubjectClient:
    """Returns canned subjects keyed by the title in the query."""

    def __init__(self, mapping):
        self.mapping = mapping

    def search_keyword(self, phrase, limit=25):
        for title, subjects in self.mapping.items():
            if title.lower() in phrase.lower():
                return [Book(key="/works/" + title, title=title, subjects=subjects)]
        return []

    def search_subject(self, subject, limit=40):
        return []


def test_profile_from_history_chases_loved_avoids_disliked():
    entries = [
        HistoryEntry("Loved", rating=5),
        HistoryEntry("Hated", rating=1),
    ]
    client = _SubjectClient({
        "Loved": ["cybernetics", "systems"],
        "Hated": ["romance", "melodrama"],
    })
    profile = profile_from_history(entries, client)
    assert profile.subjects["cybernetics"] > 0     # chase what you loved
    assert profile.avoid["romance"] > 0            # ease off what you hated
    assert "Loved" in profile.exclude and "Hated" in profile.exclude


def test_avoidance_penalises_disliked_themes():
    loved = TasteProfile()
    loved.add_subject("systems")
    loved.add_avoid("romance", weight=2)
    on_theme = Book(key="a", title="A", subjects=["systems"])
    disliked = Book(key="b", title="B", subjects=["systems", "romance"])
    s_on = scoring.score_book(on_theme, loved)
    s_dis = scoring.score_book(disliked, loved)
    # Same relevant thread, but the second also hits an avoided one -> ranks lower.
    assert s_on.score > s_dis.score


def test_annas_archive_url_is_a_search_link():
    b = Book(key="/works/X", title="The Peregrine", authors=["J. A. Baker"])
    url = b.annas_archive_url
    assert url.startswith("https://annas-archive.org/search?q=")
    assert "Peregrine" in url


# --- critiquing / refinement ------------------------------------------------

from deepshelf.cli import _apply_critique  # noqa: E402


def test_critique_dials_steer_profile():
    p = TasteProfile()
    assert _apply_critique(p, "obscure", [])
    assert p.popularity_lean < 0
    assert _apply_critique(p, "older", [])
    assert p.era_bias < 0
    assert _apply_critique(p, "stranger", [])
    assert p.adventurousness > 0.4


def test_critique_add_and_exclude():
    p = TasteProfile()
    assert _apply_critique(p, "+lighthouses", [])
    assert "lighthouses" in p.subjects
    assert _apply_critique(p, "-Moby Dick", [])
    assert "Moby Dick" in p.exclude


def test_critique_more_like_pulls_subjects():
    p = TasteProfile()
    from deepshelf.scoring import Scored
    b = Book(key="/works/X", title="Seed", subjects=["hauntology", "ruins"])
    scored = Scored(book=b, score=1.0, match=0.5, popularity=0.2, recency=0.3,
                    quality=0.8, serendipity=0.0, reasons=[])
    assert _apply_critique(p, "more like 1", [scored])
    assert "hauntology" in p.subjects
    assert "Seed" in p.exclude  # don't recommend the seed back


def test_critique_rejects_gibberish():
    p = TasteProfile()
    assert _apply_critique(p, "flibbertigibbet", []) is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
