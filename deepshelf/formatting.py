"""Terminal rendering.  Colour is optional and auto-disabled when piped."""

from __future__ import annotations

import os
import sys
from typing import List

from .scoring import Scored


class _Palette:
    def __init__(self, enabled: bool):
        self.on = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.on else text

    def bold(self, t):
        return self._wrap("1", t)

    def dim(self, t):
        return self._wrap("2", t)

    def cyan(self, t):
        return self._wrap("36", t)

    def yellow(self, t):
        return self._wrap("33", t)

    def green(self, t):
        return self._wrap("32", t)

    def magenta(self, t):
        return self._wrap("35", t)


def _palette() -> _Palette:
    enabled = (
        sys.stdout.isatty()
        and os.environ.get("NO_COLOR") is None
        and os.environ.get("TERM") != "dumb"
    )
    return _Palette(enabled)


def _bar(value: float, width: int = 10, fill: str = "█", empty: str = "·") -> str:
    n = max(0, min(width, round(value * width)))
    return fill * n + empty * (width - n)


def render(results: List[Scored], profile, show_scores: bool = False) -> str:
    p = _palette()
    lines: List[str] = []
    lines.append("")
    lines.append(p.bold(p.cyan("  DEEPSHELF — dispatches from the deep shelves")))
    lines.append(p.dim("  " + profile.summary()))
    if getattr(profile, "emergent", None):
        lines.append(
            p.magenta("  I read between your answers: ")
            + p.dim("; ".join(profile.emergent))
        )
    lines.append("")

    if not results:
        lines.append(p.yellow("  Nothing surfaced. Try broader threads or --offline."))
        lines.append("")
        return "\n".join(lines)

    for i, s in enumerate(results, 1):
        b = s.book
        year = f" ({b.year})" if b.year else ""
        badge = p.magenta(" ✦ curated") if b.curated else ""
        wild = p.yellow(" ⟡ wildcard") if getattr(s, "wildcard", False) else ""
        title = p.bold(b.title)
        lines.append(f"  {p.yellow(f'{i:>2}.')} {title}{year}{badge}{wild}")
        lines.append(f"      {p.dim('by')} {b.author_line}")

        if b.note:
            lines.append(f"      {p.dim(b.note)}")

        if s.reasons:
            lines.append("      " + p.green("· " + "  · ".join(s.reasons)))

        free = b.read_free_url
        if free:
            lines.append(f"      {p.cyan('read free:')} {free}")
        annas_label = p.cyan("Anna's Archive:")
        lines.append(f"      {annas_label} {b.annas_archive_url}")
        lines.append(f"      {p.dim(b.url)}")

        if show_scores:
            lines.append(
                "      "
                + p.dim(
                    f"score {s.score:+.2f}  "
                    f"match {_bar(s.match)}  "
                    f"popularity {_bar(s.popularity)}  "
                    f"recency {_bar(s.recency)}"
                )
            )
        lines.append("")

    lines.append(
        p.dim(
            "  Popularity and recency were considered, not penalised — "
            "tilt them with --lean and --era. "
            "Sources: Open Library + curated deep cuts."
        )
    )
    lines.append("")
    return "\n".join(lines)
