"""A thin, dependency-free client for Open Library — one of the deepest open
catalogues of human bookmaking (tens of millions of works, much of it scanned
and readable in full on the Internet Archive).

Uses only the standard library so the tool installs with zero pip footprint.
Responses are cached on disk so repeated runs are fast and gentle on the API.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

SEARCH_URL = "https://openlibrary.org/search.json"
USER_AGENT = "deepshelf/1.0 (open-source book recommender; contact via repo)"

# The fields we pull.  Everything here feeds either the score or the display.
FIELDS = ",".join(
    [
        "key",
        "title",
        "author_name",
        "first_publish_year",
        "edition_count",
        "ratings_count",
        "ratings_average",
        "readinglog_count",
        "want_to_read_count",
        "already_read_count",
        "language",
        "subject",
        "ia",
        "public_scan_b",
        "cover_i",
    ]
)


# Open Library subject tags are a mix of the useful ("cybernetics") and the
# administrative or hopelessly broad ("accessible book", "fiction", "new york
# times bestseller").  The latter pollute thematic matching, so we drop them.
_JUNK_EXACT = {
    "fiction", "general", "literature", "reading", "large print books",
    "fiction, general", "nyt:", "textbooks", "history and criticism",
}
_JUNK_SUBSTRINGS = (
    "accessible book", "protected daisy", "in library", "large type",
    "overdrive", "nyt:", "new york times", "bestseller", "reading level",
    "lending library", "internet archive", "wishlist", "browserlending",
    "print disabled", "staff picks", "translations into", "translations from",
    " authors", "fiction in ", ", fiction", "specimens", "open library",
    "accessible_book",
)


def _clean_subjects(subjects: List[str]) -> List[str]:
    out: List[str] = []
    for s in subjects:
        low = s.strip().lower()
        if not low or low in _JUNK_EXACT:
            continue
        if any(frag in low for frag in _JUNK_SUBSTRINGS):
            continue
        out.append(low)
    return out


@dataclass
class Book:
    """A candidate work, normalised from an Open Library search document."""

    key: str
    title: str
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    edition_count: int = 0
    ratings_count: int = 0
    ratings_average: Optional[float] = None
    readinglog_count: int = 0
    subjects: List[str] = field(default_factory=list)
    languages: List[str] = field(default_factory=list)
    ia_ids: List[str] = field(default_factory=list)
    public_scan: bool = False
    #: Which of our queries surfaced this book (for match scoring / provenance).
    found_via: List[str] = field(default_factory=list)
    #: True when the book comes from Deepshelf's hand-curated deep-cuts corpus.
    curated: bool = False
    #: A curator's one-line note, shown for curated picks.
    note: Optional[str] = None

    @property
    def author_line(self) -> str:
        return ", ".join(self.authors) if self.authors else "Unknown"

    @property
    def read_free_url(self) -> Optional[str]:
        if self.public_scan and self.ia_ids:
            return f"https://archive.org/details/{self.ia_ids[0]}"
        return None

    @property
    def annas_archive_url(self) -> str:
        """A search link into Anna's Archive, which aggregates open and
        shadow-library full-text sources across many formats."""
        q = urllib.parse.quote_plus(f"{self.title} {self.author_line}".strip())
        return f"https://annas-archive.org/search?q={q}"

    @property
    def url(self) -> str:
        # Live works have keys like "/works/OL123W"; curated-only entries don't
        # carry a real Open Library key, so link to a title+author search.
        if self.key.startswith("/"):
            return f"https://openlibrary.org{self.key}"
        q = urllib.parse.quote_plus(f"{self.title} {self.author_line}")
        return f"https://openlibrary.org/search?q={q}"

    @classmethod
    def from_doc(cls, doc: dict, found_via: str) -> "Book":
        return cls(
            key=doc.get("key", ""),
            title=doc.get("title", "(untitled)"),
            authors=doc.get("author_name", []) or [],
            year=doc.get("first_publish_year"),
            edition_count=doc.get("edition_count", 0) or 0,
            ratings_count=doc.get("ratings_count", 0) or 0,
            ratings_average=doc.get("ratings_average"),
            readinglog_count=doc.get("readinglog_count", 0) or 0,
            subjects=_clean_subjects(doc.get("subject") or [])[:40],
            languages=doc.get("language", []) or [],
            ia_ids=doc.get("ia", []) or [],
            public_scan=bool(doc.get("public_scan_b")),
            found_via=[found_via],
        )


class OpenLibraryClient:
    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        timeout: float = 20.0,
        offline: bool = False,
    ):
        self.cache_dir = cache_dir or (Path.home() / ".cache" / "deepshelf")
        self.timeout = timeout
        self.offline = offline
        if not offline:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    # -- public API ---------------------------------------------------------

    def search_subject(self, subject: str, limit: int = 40) -> List[Book]:
        """Books tagged with an Open Library subject."""
        docs = self._get({"q": f'subject:"{subject}"', "limit": str(limit)})
        return [Book.from_doc(d, f"subject:{subject}") for d in docs]

    def search_keyword(self, phrase: str, limit: int = 25) -> List[Book]:
        """Free-text search across the catalogue."""
        docs = self._get({"q": phrase, "limit": str(limit)})
        return [Book.from_doc(d, f"kw:{phrase}") for d in docs]

    # -- internals ----------------------------------------------------------

    def _get(self, params: dict) -> List[dict]:
        params = {**params, "fields": FIELDS}
        query = urllib.parse.urlencode(params)
        url = f"{SEARCH_URL}?{query}"

        cached = self._read_cache(url)
        if cached is not None:
            return cached.get("docs", [])
        if self.offline:
            return []

        payload = self._fetch(url)
        if payload is None:
            return []
        self._write_cache(url, payload)
        return payload.get("docs", [])

    def _fetch(self, url: str) -> Optional[dict]:
        backoff = 1.0
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                if attempt == 3:
                    # Fail soft: the recommender still has its curated corpus.
                    import sys

                    print(f"  (network: {exc}; falling back)", file=sys.stderr)
                    return None
                time.sleep(backoff)
                backoff *= 2
        return None

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        return self.cache_dir / f"{digest}.json"

    def _read_cache(self, url: str, max_age_days: float = 30.0) -> Optional[dict]:
        path = self._cache_path(url)
        if not path.exists():
            return None
        try:
            age_days = (time.time() - path.stat().st_mtime) / 86400.0
            if age_days > max_age_days:
                return None
            return json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            return None

    def _write_cache(self, url: str, payload: dict) -> None:
        try:
            self._cache_path(url).write_text(json.dumps(payload), "utf-8")
        except OSError:
            pass
