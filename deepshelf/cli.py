"""Command-line interface for Deepshelf.

Two ways to drive it:

  deepshelf                       # the full creative interview, then picks
  deepshelf --quick               # a fast three-question probe
  deepshelf --subject cybernetics --subject "nature writing"
  deepshelf --answer doorway=2 --answer obsession="lighthouses, grief"

Tuning dials (all optional leans — popularity and recency are always
considered, never used as automatic penalties):
  --lean obscure|balanced|popular   tilt toward the little- or well-known
  --era old|new|any                 tilt the ranking in time
  --adventurous 0.7                 more serendipitous jitter (0..1)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List

from . import __version__
from .formatting import render
from .interview import quick_profile, run_interactive
from .openlibrary import OpenLibraryClient
from .profile import TasteProfile
from .recommender import recommend

_QUICK_KEYS = ["doorway_appeal", "tone", "obsession"]

_ERA_MAP = {"old": -0.6, "new": 0.5, "any": 0.0}
_LEAN_MAP = {"obscure": -0.6, "balanced": 0.0, "popular": 0.6}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="deepshelf",
        description="Book recommendations from the deep shelves — "
        "weighed against popularity and recency.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"deepshelf {__version__}")

    mode = p.add_argument_group("how to probe")
    mode.add_argument(
        "--quick", action="store_true", help="short three-question probe"
    )
    mode.add_argument(
        "--answer",
        action="append",
        default=[],
        metavar="key=value",
        help="answer an interview question non-interactively (repeatable)",
    )
    mode.add_argument(
        "--subject",
        action="append",
        default=[],
        metavar="SUBJECT",
        help="seed a subject/thread directly (repeatable)",
    )
    mode.add_argument(
        "--keyword",
        action="append",
        default=[],
        metavar="PHRASE",
        help="seed a free-text search phrase (repeatable)",
    )
    mode.add_argument(
        "--history",
        metavar="FILE",
        help="build a profile from books you've read + ratings "
             "(JSON, or a Goodreads/generic CSV export). Excludes read titles, "
             "chases loved subjects, eases off disliked ones.",
    )

    dials = p.add_argument_group("tuning dials (all leans, never filters)")
    dials.add_argument("--lean", choices=list(_LEAN_MAP),
                       help="tilt toward the little-known, a balance, or the "
                            "well-loved (default: balanced — popularity is "
                            "considered but not weighed for or against)")
    dials.add_argument("--popularity-lean", type=float, metavar="-1..1",
                       help="fine-grained popularity tilt; -1 obscure .. +1 popular")
    dials.add_argument("--era", choices=list(_ERA_MAP),
                       help="tilt the ranking in time (default: any era)")
    dials.add_argument("--adventurous", type=float, metavar="0..1",
                       help="serendipity jitter (default 0.4)")
    dials.add_argument("--exclude", action="append", default=[], metavar="TITLE",
                       help="a title you've already read (repeatable)")
    dials.add_argument("--lang", action="append", default=[], metavar="ISO",
                       help="preferred language code, e.g. eng (repeatable)")

    out = p.add_argument_group("output & data")
    out.add_argument("-n", "--limit", type=int, default=8, help="how many picks")
    out.add_argument("--scores", action="store_true", help="show score breakdowns")
    out.add_argument("--offline", action="store_true",
                     help="use only the curated corpus + cache; no network")
    out.add_argument("--cache-dir", type=Path, help="where to cache API responses")
    out.add_argument("--no-diversify", action="store_true",
                     help="allow one author to dominate the shelf")
    out.add_argument("--refine", action="store_true",
                     help="after the picks, keep steering: 'more like 2', "
                          "'stranger', 'older', 'obscure', '+ghosts', '-Dune'")
    return p


def _parse_answers(pairs: List[str]) -> Dict[str, str]:
    answers: Dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--answer expects key=value, got: {pair!r}")
        key, val = pair.split("=", 1)
        answers[key.strip()] = val.strip()
    return answers


def _build_profile(args) -> TasteProfile:
    seeded = bool(args.answer or args.subject or args.keyword)

    if args.quick and not seeded:
        # Ask only the quick subset interactively.
        from .interview import QUESTIONS, _apply_choice, synthesize  # noqa

        profile = TasteProfile()
        by_key = {q.key: q for q in QUESTIONS}
        print("\n  A quick three-question probe. Enter to skip.\n")
        for key in _QUICK_KEYS:
            q = by_key[key]
            print(q.prompt)
            if q.freeform is None:
                for i, opt in enumerate(q.options, 1):
                    print(f"    {i}. {opt.label}")
            raw = input("  > ").strip()
            print("")
            if q.freeform is not None:
                if raw:
                    q.freeform(profile, raw)
            else:
                _apply_choice(profile, q, raw)
        return synthesize(profile)

    if seeded:
        profile = quick_profile(_parse_answers(args.answer))
        for s in args.subject:
            profile.add_subject(s, weight=1.2)
        for k in args.keyword:
            profile.add_keyword(k)
        return profile

    # Default: the full interactive interview.
    return run_interactive()


def _apply_dials(profile: TasteProfile, args) -> None:
    if args.lean is not None:
        profile.popularity_lean = _LEAN_MAP[args.lean]
    if args.popularity_lean is not None:
        profile.popularity_lean = max(-1.0, min(1.0, args.popularity_lean))
    if args.adventurous is not None:
        profile.adventurousness = max(0.0, min(1.0, args.adventurous))
    if args.era is not None:
        profile.era_bias = _ERA_MAP[args.era]
    for title in args.exclude:
        profile.exclude.add(title)
    profile.languages.extend(args.lang)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    seeded = bool(args.answer or args.subject or args.keyword or args.quick)
    # With --history and nothing else, build purely from the reader's shelf and
    # skip the interview.
    history_only = bool(args.history) and not seeded
    profile = TasteProfile() if history_only else _build_profile(args)
    _apply_dials(profile, args)

    client = OpenLibraryClient(cache_dir=args.cache_dir, offline=args.offline)

    if args.history:
        from .history import load_history, profile_from_history
        try:
            entries = load_history(args.history)
        except (OSError, ValueError) as exc:
            raise SystemExit(f"could not read --history {args.history!r}: {exc}")
        profile = profile_from_history(entries, client, into=profile)
        print(f"  Learned from {len(entries)} books in your history.")

    # If the reader gave us nothing to go on, widen with a default palette
    # rather than returning noise.
    if not profile.subjects and not profile.keywords:
        for s in ["essays", "the uncanny", "nature writing", "modernism"]:
            profile.add_subject(s, weight=0.6)

    def run():
        return recommend(
            profile, client=client, limit=args.limit,
            diversify=not args.no_diversify,
        )

    results = run()
    sys.stdout.write(render(results, profile, show_scores=args.scores))

    if args.refine and sys.stdin.isatty():
        _refine_loop(profile, results, run, args)
    return 0


# --- Critiquing / refinement -------------------------------------------------
#
# Conversational recommenders do their best work when the user can *steer* after
# seeing results — critiquing attributes ("like this, but stranger") rather than
# restating the whole query (Jannach et al. 2021, ACM Computing Surveys).

_REFINE_HELP = (
    "  steer:  more like N | stranger | safer | older | newer | obscure | "
    "popular | warmer | darker | +<subject> | -<title> | done"
)


def _refine_loop(profile, results, run, args):
    print(_REFINE_HELP)
    last = results
    while True:
        try:
            raw = input("  refine > ").strip()
        except EOFError:
            break
        if not raw or raw.lower() in {"done", "q", "quit", "exit"}:
            break
        if raw.lower() in {"help", "?"}:
            print(_REFINE_HELP)
            continue
        if not _apply_critique(profile, raw, last):
            print("  (didn't understand that — type 'help')")
            continue
        last = run()
        sys.stdout.write(render(last, profile, show_scores=args.scores))
    return last


def _apply_critique(profile, raw, last_results) -> bool:
    """Mutate the profile from a single critique command.  Returns False if the
    command was not understood."""
    low = raw.lower()
    dial = {
        "stranger": ("adventurousness", +0.2),
        "weirder": ("adventurousness", +0.2),
        "safer": ("adventurousness", -0.2),
        "older": ("era_bias", -0.3),
        "newer": ("era_bias", +0.3),
        "obscure": ("popularity_lean", -0.3),
        "popular": ("popularity_lean", +0.3),
    }
    if low in dial:
        attr, delta = dial[low]
        profile.blend({attr: delta})
        return True
    if low in {"warmer", "darker", "bleaker", "playful"}:
        profile.tone = {"warmer": "warm", "darker": "bleak",
                        "bleaker": "bleak", "playful": "playful"}[low]
        profile.add_subject(profile.tone, weight=1.2)
        return True
    if low.startswith("more like"):
        return _more_like(profile, raw, last_results)
    if raw.startswith("+") and len(raw) > 1:
        profile.add_subject(raw[1:].strip(), weight=1.5)
        profile.add_keyword(raw[1:].strip())
        return True
    if raw.startswith("-") and len(raw) > 1:
        profile.exclude.add(raw[1:].strip())
        return True
    return False


def _more_like(profile, raw, last_results) -> bool:
    """'more like 2' — fold the chosen book's own subjects into the profile."""
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return False
    idx = int(digits) - 1
    if not (0 <= idx < len(last_results)):
        return False
    book = last_results[idx].book
    for subject in book.subjects[:6]:
        profile.add_subject(subject, weight=1.3)
    profile.exclude.add(book.title)  # don't just recommend it back
    return True


if __name__ == "__main__":
    raise SystemExit(main())
