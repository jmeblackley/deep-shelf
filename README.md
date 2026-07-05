# Deepshelf

**Book recommendations from the deep shelves.** A command-line recommender that
draws on open catalogues (Open Library / the Internet Archive) plus a
hand-curated corpus of deep cuts, *considers* popularity and recency as signals
you can steer rather than penalties, and probes your taste through oblique,
creative questions designed to spark discovery.

```
$ deepshelf
```

```
  DEEPSHELF — dispatches from the deep shelves
  You read for language, in an unsettling register. any era; toward the
  little-known; serendipity 80%. Threads: experimental fiction, secret
  history, conspiracy, paranoia, prose style.
  I read between your answers: paranoid, fragmentary, conspiratorial

   1. The Illuminatus! Trilogy (1977)
      by Robert Shea, Robert Anton Wilson
      · a lateral fit — reached via conspiracy  · known but not ubiquitous
   2. Harvest (2013)  ⟡ wildcard
      by Jim Crace
      ...
```

## What makes it different

- **Popularity and recency are considered, never penalised.** They are computed
  and shown for every book, but they only move the ranking if *you* lean on them
  (`--lean obscure|balanced|popular`, `--era old|new|any`). At the neutral
  default they inform the shelf without counting for or against any book.
- **Deep, open sources.** Live results come from
  [Open Library](https://openlibrary.org) (tens of millions of works, much of it
  free full-text on the Internet Archive), augmented by a curated corpus of
  ~38 genuinely overlooked books across fiction, philosophy, science, and
  nature writing. Works readable free are flagged with a direct link.
- **A creative interview that bridges to nuance.** Instead of "pick a genre," it
  asks oblique questions ("Which doorway do you walk toward at 2 a.m.?") *and*
  the questions the readers'-advisory field actually uses — which **doorway**
  pulls you in (character, setting, language, or story) and what **tone** you
  want. Crucially, a **synthesis layer** reads *combinations* of answers:
  `cave + one-thing-completely` becomes "an obsessive descent into a single
  subject"; `static + rumor` becomes "paranoid, fragmentary, conspiratorial."
  These emergent threads are weighted above any single answer.
- **Serendipity that stays relevant.** The "spark" is a relevant *and*
  unexpected pick — a lateral fit reached through a secondary thread, never
  irrelevant noise. Adventurous runs surface a labelled **⟡ wildcard**.
- **Critiquing loop.** With `--refine` you keep steering after the picks:
  `more like 2`, `stranger`, `older`, `obscure`, `+ghosts`, `-Dune`, `done`.
- **Learns from your shelf — no account needed.** Point `--history` at a local
  file of books you've read (including a Goodreads CSV export). Deepshelf chases
  the subjects of books you rated highly, eases off those you rated low,
  and excludes everything you've already read.
- **Find the full text.** Every pick links to
  [Anna's Archive](https://annas-archive.org) (which aggregates open and
  shadow-library sources), plus a free Internet Archive link where the scan is
  public domain.

The design choices above are grounded in peer-reviewed literature — see
[`docs/DESIGN.md`](docs/DESIGN.md).

## Install

Pure standard library, zero runtime dependencies.

```bash
pip install -e .        # provides the `deepshelf` command
# or run without installing:
python -m deepshelf
```

Requires Python 3.8+.

## Usage

```bash
deepshelf                      # the full creative interview, then picks
deepshelf --quick              # a short three-question probe
deepshelf --refine             # keep steering after the picks (critiquing)

# Non-interactive / scriptable:
deepshelf --answer doorway_appeal=3 --answer tone=4 \
          --answer obsession="maps, memory, ruins" --lean obscure -n 6

deepshelf --subject cybernetics --subject "nature writing" --scores
deepshelf --offline            # curated corpus + cache only, no network

# Personalise from your reading history + ratings:
deepshelf --history my_books.json            # [{"title","author","rating"}, ...]
deepshelf --history goodreads_export.csv     # Goodreads library export works
deepshelf --history my_books.csv --answer tone=4   # blend history with a probe
```

### Personalising from your shelf (`--history`)

No sign-in and no server — just a local file. Two formats are auto-detected:

- **JSON**: `[{"title": "Stoner", "author": "John Williams", "rating": 5}, ...]`
  (`author` and `rating` optional; 1–5 scale).
- **CSV**: a Goodreads export (`Title,Author,My Rating`) or a generic
  `title,author,rating` header.

Books you rated highly pull their subjects into your profile; books you rated
low push theirs into an *avoid* list (a gentle, personal penalty learned from
your own taste — never a blanket bias); everything listed is excluded from the
results. Combine `--history` with interview answers to sharpen the signal.

### Tuning dials (all leans, never filters)

| Flag | Effect |
|------|--------|
| `--lean obscure\|balanced\|popular` | tilt toward the little- or well-known (default: balanced) |
| `--era old\|new\|any` | tilt the ranking in time (default: any) |
| `--adventurous 0..1` | appetite for relevant-but-unexpected picks |
| `--exclude "TITLE"` | a book you've already read (repeatable) |
| `--lang eng` | preferred language code (repeatable) |
| `-n, --limit` | how many picks |
| `--history FILE` | build the profile from books you've read + ratings |
| `--refine` | keep steering after the picks (critiquing loop) |
| `--scores` | show the score breakdown per pick |

## How a book is scored

Every candidate is described by signals normalised to ~0..1, then combined:

```
score =  1.2 · thematic_match          how many of your threads run through it
       + quality  (gated by relevance) good — but only if it's actually for you
       + free_bonus                     readable free on the Internet Archive
       + popularity_lean · popularity   YOUR tilt; 0 at the neutral default
       + era_bias · recency             YOUR tilt; 0 at the neutral default
       + adventurousness · match · unexpectedness    the serendipity spark
```

A **relevance floor** ensures a highly-rated but off-theme book can't ride its
rating onto the shelf. Popularity and recency contribute *nothing* unless you
lean on them. Serendipity is multiplied by relevance, so it can only ever
reward a lateral fit — never noise.

## Development

```bash
pip install pytest
python -m pytest tests/ -q      # 38 tests, fully offline (no network)
```

## Data & sources

- Live catalogue: Open Library search API (cached on disk for 30 days).
- Curated corpus: `deepshelf/data/deep_cuts.json` — edit or extend it freely.
- Full-text links point to the Internet Archive where available.
