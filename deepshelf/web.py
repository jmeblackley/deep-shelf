"""A tiny, dependency-free web server that puts a friendly face on Deepshelf.

``deepshelf --serve`` starts it.  It serves the single-page UI (``web/index.html``)
and one JSON endpoint, ``/api/recommend``, that runs the *real* Python
recommender against the live Open Library catalogue.  The same page also works
opened straight from disk — it simply falls back to the embedded curated corpus
when no server is present.

Standard library only: no Flask, no build step.
"""

from __future__ import annotations

import json
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .openlibrary import OpenLibraryClient
from .profile import TasteProfile
from .recommender import recommend
from .scoring import unexpectedness

_INDEX = Path(__file__).parent / "web" / "index.html"


def _profile_from_payload(data: dict) -> TasteProfile:
    p = TasteProfile()
    p.subjects = Counter({str(k): float(v) for k, v in (data.get("subjects") or {}).items()})
    p.keywords = [str(k) for k in (data.get("keywords") or [])]
    p.popularity_lean = _clampf(data.get("lean", 0.0), -1, 1)
    p.era_bias = _clampf(data.get("era", 0.0), -1, 1)
    p.adventurousness = _clampf(data.get("adv", 0.4), 0, 1)
    p.doorway = str(data.get("doorway", ""))
    p.tone = str(data.get("tone", ""))
    # Default to an English lean unless the client opts out or names languages.
    langs = data.get("languages")
    if langs:
        p.languages = [str(l) for l in langs]
    elif not data.get("all_languages"):
        p.languages = ["eng"]
    return p


def _clampf(v, lo, hi):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return lo


def _pick_to_json(scored, profile) -> dict:
    b = scored.book
    return {
        "title": b.title,
        "author": b.author_line,
        "year": b.year,
        "subjects": b.subjects[:8],
        "note": b.note,
        "curated": b.curated,
        "popularity": round(scored.popularity, 4),
        "recency": round(scored.recency, 4),
        "match": round(scored.match, 4),
        "serendipity": round(scored.serendipity, 4),
        "wildcard": scored.wildcard,
        "annas_url": b.annas_archive_url,
        "openlibrary_url": b.url,
        "free_url": b.read_free_url,
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "deepshelf"

    def log_message(self, *args):  # keep the console quiet
        pass

    def _send(self, code, body, ctype="application/json"):
        payload = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            try:
                self._send(200, _INDEX.read_text("utf-8"), "text/html; charset=utf-8")
            except OSError:
                self._send(500, "index.html missing", "text/plain")
        elif self.path == "/api/health":
            self._send(200, json.dumps({"ok": True}))
        elif self.path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if self.path != "/api/recommend":
            self._send(404, json.dumps({"error": "not found"}))
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            self._send(400, json.dumps({"error": "bad json"}))
            return
        profile = _profile_from_payload(data)
        limit = int(data.get("limit", 8))
        client = OpenLibraryClient(offline=bool(data.get("offline")))
        picks = recommend(profile, client=client, limit=limit)
        body = {"picks": [_pick_to_json(s, profile) for s in picks]}
        self._send(200, json.dumps(body))


def serve(port: int = 8000, host: str = "127.0.0.1") -> None:
    httpd = ThreadingHTTPServer((host, port), _Handler)
    url = f"http://{host}:{port}"
    print(f"\n  Deepshelf is open at  {url}")
    print("  Press Ctrl+C to close the reading room.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Closed.\n")
        httpd.shutdown()
