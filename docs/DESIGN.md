# Design notes & literature basis

Deepshelf's design is deliberately grounded in the recommender-systems and
readers'-advisory research literature. This document records the decisions that
matter and the peer-reviewed work behind them, so the choices can be audited and
challenged.

## 1. Popularity and recency are *considered*, not penalised

An early version of this tool subtracted popularity and recency from a book's
score. That is a blunt instrument: it trades one bias (toward the popular) for
its mirror image (against it), and it can bury a book a reader would genuinely
love simply because other people also love it.

The current design treats popularity and recency as **neutral signals**. They
are always computed and displayed, but they enter the ranking *only* through a
reader-set lean (`popularity_lean`, `era_bias`), which is `0` by default. At the
default, an identical popular and obscure book score equally
(`tests/test_deepshelf.py::test_neutral_lean_does_not_penalise_popularity`). This
matches the beyond-accuracy framing in the literature, where novelty and
diversity are objectives to *balance*, not to maximise blindly, and where
"showing random irrelevant content for novelty's sake" is an explicit
anti-pattern.

> Kaminskas, M. & Bridge, D. (2016). *Diversity, Serendipity, Novelty, and
> Coverage: A Survey and Empirical Analysis of Beyond-Accuracy Objectives in
> Recommender Systems.* ACM Transactions on Interactive Intelligent Systems
> 7(1), Article 2. https://doi.org/10.1145/2926720

## 2. Serendipity = relevance × unexpectedness (the "spark")

The clearest, most consistent finding across the serendipity literature is that
a serendipitous recommendation is **both relevant and unexpected** — not merely
novel, and certainly not merely obscure. Deepshelf implements this directly:

```
serendipity = adventurousness · thematic_match · unexpectedness
```

Because the term is *multiplied by relevance*, it can never lift an irrelevant
book; it only rewards a **lateral fit** — a book that connects through a
secondary thread rather than the one or two obvious ones
(`scoring.unexpectedness`). A **relevance floor** in the recommender
(`_apply_relevance_floor`) additionally prevents a highly-rated but off-theme
book from riding its rating onto the shelf — the exact failure mode a naive
accuracy score produces. This is verified in
`test_serendipity_requires_relevance` and
`test_relevance_floor_filters_high_rated_noise`.

> Ziarani, R. J. & Ravanmehr, R. (2021). *Serendipity in Recommender Systems: A
> Systematic Literature Review.* Journal of Computer Science and Technology
> 36(2), 375–396. https://doi.org/10.1007/s11390-020-0135-9
>
> Kotkov, D., Wang, S. & Veijalainen, J. (2016). *A survey of serendipity in
> recommender systems.* Knowledge-Based Systems 111, 180–192.
> https://doi.org/10.1016/j.knosys.2016.08.014

Serendipitous picks are also **explained** ("a lateral fit — reached via
conspiracy") and labelled as wildcards, because the literature notes that an
unexpected recommendation needs a rationale to land as delight rather than
confusion (Kaminskas & Bridge, 2016).

## 3. The interview: appeal-based elicitation, not genre buckets

The readers'-advisory field has long argued that the useful question is not
*what a book is about* but *what draws a reader in*. Deepshelf captures this in
two first-class dimensions:

- **Doorway** — the reader's primary axis of appeal: character, setting,
  language, or story (Nancy Pearl's "doorways", a practitioner framework widely
  used in libraries).
- **Tone** — the emotional register (a Saricks "appeal factor").

The empirical and theoretical case for treating *appeal* (rather than genre or
subject) as the unit of recommendation is made in:

> Dali, K. (2014). *From Book Appeal to Reading Appeal: Redefining the Concept of
> Appeal in Readers' Advisory.* The Library Quarterly 84(1), 22–48.
> https://doi.org/10.1086/674034
>
> Saricks, J. G. (2005). *Readers' Advisory Service in the Public Library*
> (3rd ed.). ALA Editions. — the canonical statement of the appeal factors
> (pacing, characterization, story line, frame/tone, style).

Pearl's "doorways" and Saricks' "appeal factors" are professional/practitioner
LIS frameworks (books), not peer-reviewed articles; the peer-reviewed support for
building recommendation on *reading appeal* is Dali (2014), above.

### Bridging answers to nuance: the synthesis layer

Individual answers map to broad subjects. The **synthesis layer**
(`interview.COMBOS` / `synthesize`) reads *combinations* of answers to infer a
specific sensibility no single answer names — e.g. `static + rumor` →
"paranoid, fragmentary, conspiratorial", injecting `conspiracy`,
`experimental fiction`, `paranoia`, `secret history`. Emergent threads are
weighted **above** raw answers, because a coincidence of signals is a stronger
signal than any one of them
(`test_synthesis_is_emergent_not_additive`). This is a deliberate move away from
purely additive attribute elicitation toward something closer to how a skilled
readers'-advisory interview interprets a reader.

## 4. Critiquing: let the reader steer after seeing results

The conversational-recommender literature finds that users do their best work
when they can *critique* results ("like this, but stranger") rather than restate
the whole query, and that higher-guidance elicitation yields better matches.
`deepshelf --refine` implements an attribute-critiquing loop (`more like 2`,
`stranger`, `older`, `obscure`, `+subject`, `-title`).

> Jannach, D., Manzoor, A., Cai, W. & Chen, L. (2021). *A Survey on Conversational
> Recommender Systems.* ACM Computing Surveys 54(5), Article 105.
> https://doi.org/10.1145/3453154
>
> Preference-elicitation UX (guidance → match): *The effect of preference
> elicitation methods on the user experience in conversational recommender
> systems.* Computer Speech & Language (2024).
> https://doi.org/10.1016/j.csl.2024.101671

## 5. Personalisation from history + ratings (content-based)

`--history` builds the profile from the reader's own shelf: subjects of
highly-rated books are chased, subjects of poorly-rated books are eased off (an
`avoid` penalty), and every read title is excluded. This is textbook
content-based filtering — recommending items whose attributes resemble those the
user has previously liked — chosen deliberately over collaborative filtering
because it needs no other users, no account, and no server, and because it
degrades gracefully offline. The trade-offs of content-based vs. collaborative
approaches are surveyed in Jannach et al. (2021, above) and the broader RS
literature. The `avoid` term is a *personal* signal learned from the reader's
own low ratings, which is categorically different from the popularity bias
rejected in §1.

**On accounts:** a sign-in/wishlist system is intentionally *not* built. It adds
a large security- and privacy-heavy surface (auth, storage, data protection) for
value that a local history file already delivers. Accounts become worthwhile only
for a hosted, cross-device product — a different design than this local-first CLI.

## 6. Deep, open knowledge sources

Live results come from the Open Library search API — one of the largest open
bibliographic catalogues, with a large fraction scanned and readable in full on
the Internet Archive (surfaced as free-to-read links). This is augmented by a
small hand-curated corpus (`data/deep_cuts.json`) so the tool gives excellent,
non-obvious answers even offline, and so human judgement seeds the live results.

---

### Source quality note

Every empirical or theoretical claim above is anchored to a peer-reviewed venue
(ACM TiiS, ACM Computing Surveys, Journal of Computer Science and Technology,
Knowledge-Based Systems, The Library Quarterly, Computer Speech & Language). The
two practitioner frameworks used (Pearl's doorways, Saricks' appeal factors) are
identified as such and paired with peer-reviewed support (Dali, 2014).
