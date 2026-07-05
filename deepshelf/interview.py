"""Creative probing.

Most recommenders ask "what genre do you like?".  That question flattens a
reader into a marketing category and steers straight back to the bestseller
table.  Deepshelf asks *oblique* questions instead — projective, sensory,
lateral — and reads taste sideways from the answers.

Every option carries three payloads:

* ``subjects`` — Open Library subject tags (with implicit weight = order).
* ``keywords`` — raw phrases to feed the search.
* ``tune``     — deltas applied to the continuous dials (obscurity, era, etc.).

The same question bank powers both the interactive interview and a scriptable
"quick take" where a handful of answers are passed on the command line.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .profile import TasteProfile


@dataclass
class Option:
    label: str
    subjects: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    tune: Dict[str, float] = field(default_factory=dict)
    #: A short semantic token (e.g. "cave", "rumor") recorded when this option
    #: is chosen.  The synthesis layer reads *combinations* of these tokens to
    #: infer nuanced threads no single answer expresses.
    tag: str = ""
    #: Direct assignments onto named profile fields, e.g. {"doorway": "language"}.
    #: Used for the readers'-advisory appeal axes (doorway, tone).
    sets: Dict[str, str] = field(default_factory=dict)


@dataclass
class Question:
    key: str
    prompt: str
    options: List[Option]
    #: If set, the answer is free text handed to this function instead of options.
    freeform: Optional[Callable[[TasteProfile, str], None]] = None


def _freeform_obsession(profile: TasteProfile, text: str) -> None:
    """Whatever the reader is quietly obsessed with becomes search fuel."""
    for chunk in _split_phrases(text):
        profile.add_keyword(chunk)
        profile.add_subject(chunk, weight=0.8)


def _split_phrases(text: str) -> List[str]:
    parts: List[str] = []
    for piece in text.replace(";", ",").split(","):
        piece = piece.strip()
        if piece:
            parts.append(piece)
    return parts


# --- The question bank ------------------------------------------------------
#
# These are intentionally strange.  The mapping from answer -> subjects is a
# curatorial act: each door opens onto a different region of the stacks.

QUESTIONS: List[Question] = [
    Question(
        key="doorway",
        prompt=(
            "It is 2 a.m. and you cannot sleep. Which doorway do you walk toward?"
        ),
        options=[
            Option(
                "A library that is very quietly on fire",
                subjects=["philosophy", "essays", "aphorisms", "memory"],
                keywords=["fragments", "notebooks"],
                tag="burning-library",
            ),
            Option(
                "A cave with a cold draft coming from deeper in",
                subjects=["exploration", "caves", "geology", "the unknown"],
                keywords=["descent", "underworld"],
                tune={"adventurousness": 0.15},
                tag="cave",
            ),
            Option(
                "A lit window across a dark courtyard",
                subjects=["domestic fiction", "loneliness", "cities", "windows"],
                keywords=["strangers", "apartment"],
                tag="window",
            ),
            Option(
                "A door in a tree that was not there yesterday",
                subjects=["fantasy", "folklore", "fairy tales", "the uncanny"],
                keywords=["threshold", "otherworld"],
                tune={"adventurousness": 0.2},
                tag="tree-door",
            ),
        ],
    ),
    Question(
        key="trust",
        prompt="Which do you trust more?",
        options=[
            Option(
                "A map",
                subjects=["science", "systems", "mathematics", "history"],
                keywords=["structure", "cartography"],
                tag="map",
            ),
            Option(
                "A rumor",
                subjects=["folklore", "oral tradition", "secret history", "occult"],
                keywords=["hearsay", "apocrypha"],
                # Wanting apocrypha is an explicit tilt toward the overlooked.
                tune={"popularity_lean": -0.2, "adventurousness": 0.15},
                tag="rumor",
            ),
            Option(
                "A scar",
                subjects=["memoir", "trauma", "the body", "war"],
                keywords=["witness", "aftermath"],
                tag="scar",
            ),
            Option(
                "A joke",
                subjects=["satire", "comedy", "absurdist fiction", "wit"],
                keywords=["farce", "the absurd"],
                tune={"adventurousness": 0.1},
                tag="joke",
            ),
        ],
    ),
    Question(
        key="texture",
        prompt="Pick a texture you'd want the prose to feel like:",
        options=[
            Option(
                "Gravel underfoot",
                subjects=["realism", "working class", "rural life"],
                keywords=["plainspoken", "grit"],
                tag="gravel",
            ),
            Option(
                "Static on an old radio",
                subjects=["experimental fiction", "surrealism", "sound"],
                keywords=["fragmentary", "interference"],
                tune={"adventurousness": 0.2},
                tag="static",
            ),
            Option(
                "Cold glass",
                subjects=["modernism", "architecture", "precision", "detachment"],
                keywords=["clean", "clinical"],
                tag="glass",
            ),
            Option(
                "Moss on stone",
                subjects=["nature writing", "ecology", "slowness", "landscape"],
                keywords=["patient", "overgrown"],
                tag="moss",
            ),
        ],
    ),
    Question(
        key="hunger",
        prompt="You have one evening. Would you rather...",
        options=[
            Option(
                "Understand one small thing completely",
                subjects=["monograph", "natural history", "craft", "obsession"],
                keywords=["deep dive", "single subject"],
                tag="deep",
            ),
            Option(
                "Glimpse a thousand things at speed",
                subjects=["encyclopedic fiction", "essays", "miscellany"],
                keywords=["panorama", "catalogue"],
                tune={"adventurousness": 0.15},
                tag="broad",
            ),
        ],
    ),
    Question(
        key="company",
        prompt="Which narrator would you follow into a bad neighborhood?",
        options=[
            Option(
                "The unreliable one",
                subjects=["unreliable narrator", "psychological fiction", "noir"],
                keywords=["deception", "confession"],
                tag="unreliable",
            ),
            Option(
                "The one who has clearly given up",
                subjects=["existentialism", "melancholy", "outsider"],
                keywords=["resignation", "drift"],
                tag="given-up",
            ),
            Option(
                "The one who won't stop noticing details",
                subjects=["observation", "phenomenology", "everyday life"],
                keywords=["attention", "the ordinary"],
                tag="noticer",
            ),
            Option(
                "The one who might be a ghost",
                subjects=["ghost stories", "haunting", "the gothic", "memory"],
                keywords=["revenant", "the past"],
                tune={"adventurousness": 0.1},
                tag="ghost",
            ),
        ],
    ),
    Question(
        key="era",
        prompt="A book arrives from where in time? (a preference, not a filter)",
        options=[
            Option(
                "Dredged up from before anyone you know was born",
                subjects=["classics", "antiquity"],
                keywords=["old"],
                tune={"era_bias": -0.4},
                tag="ancient",
            ),
            Option(
                "The strange middle decades nobody remembers",
                subjects=["mid-century", "modernism"],
                keywords=["overlooked"],
                # 'nobody remembers' is an explicit lean toward the little-known.
                tune={"era_bias": -0.15, "popularity_lean": -0.2},
                tag="mid-century",
            ),
            Option(
                "Still warm from the present",
                subjects=["contemporary"],
                keywords=["new voices"],
                tune={"era_bias": 0.35},
                tag="present",
            ),
            Option(
                "Doesn't matter — surprise me across time",
                subjects=[],
                keywords=[],
                tag="any-era",
            ),
        ],
    ),
    Question(
        key="familiarity",
        prompt=(
            "How do you feel about a book everyone already knows? (a lean, not a "
            "rule — popularity is always just one factor)"
        ),
        options=[
            Option(
                "Steer me off the beaten path",
                subjects=[],
                keywords=[],
                tune={"popularity_lean": -0.5},
                tag="familiarity-low",
            ),
            Option(
                "I don't mind either way — surprise me",
                subjects=[],
                keywords=[],
                # Neutral by design: leaves popularity considered but not tilted.
                tune={},
                tag="familiarity-neutral",
            ),
            Option(
                "I'd happily read a beloved favourite",
                subjects=[],
                keywords=[],
                tune={"popularity_lean": 0.5},
                tag="familiarity-high",
            ),
        ],
    ),
    Question(
        # Nancy Pearl's "doorways": the reader's primary axis of appeal.  The
        # readers'-advisory literature stresses asking what *draws you in*, not
        # what a book is *about* (Dali 2014, The Library Quarterly; Saricks 2005).
        key="doorway_appeal",
        prompt="When a book truly grabs you, what pulled you in?",
        options=[
            Option(
                "The people — I live inside characters",
                subjects=["character study", "psychological fiction",
                          "biography", "interior life"],
                keywords=["unforgettable characters"],
                tag="door-character",
                sets={"doorway": "character"},
            ),
            Option(
                "The place — I want to be transported somewhere",
                subjects=["setting", "atmosphere", "landscape", "travel",
                          "sense of place"],
                keywords=["strong sense of place"],
                tag="door-setting",
                sets={"doorway": "setting"},
            ),
            Option(
                "The language — sentences I want to read aloud",
                subjects=["prose style", "poetry", "literary fiction",
                          "modernism"],
                keywords=["sentence-level beauty"],
                tag="door-language",
                sets={"doorway": "language"},
            ),
            Option(
                "The story — I need to know what happens next",
                subjects=["plot", "suspense", "adventure", "narrative drive"],
                keywords=["propulsive plot"],
                tag="door-story",
                sets={"doorway": "story"},
            ),
        ],
    ),
    Question(
        # A Saricks "tone" appeal factor: the emotional weather the reader wants.
        key="tone",
        prompt="What emotional weather are you in the mood for?",
        options=[
            Option(
                "Bleak and unflinching",
                subjects=["tragedy", "bleak", "existentialism"],
                keywords=["unflinching"],
                tag="tone-bleak",
                sets={"tone": "bleak"},
            ),
            Option(
                "Warm and humane",
                subjects=["hopeful", "humane", "tender"],
                keywords=["warmth", "consolation"],
                tag="tone-warm",
                sets={"tone": "warm"},
            ),
            Option(
                "Playful and strange",
                subjects=["playful", "whimsical", "absurdist fiction"],
                keywords=["playful", "inventive"],
                tag="tone-playful",
                sets={"tone": "playful"},
            ),
            Option(
                "Unsettling — keep me off balance",
                subjects=["unsettling", "the uncanny", "psychological fiction"],
                keywords=["dread", "off-kilter"],
                tag="tone-unsettling",
                sets={"tone": "unsettling"},
            ),
        ],
    ),
    Question(
        key="obsession",
        prompt=(
            "Name something you are quietly obsessed with — a place, a craft, an "
            "idea, a fear. (comma-separated is fine)"
        ),
        options=[],
        freeform=_freeform_obsession,
    ),
]


# --- The synthesis layer ----------------------------------------------------
#
# This is where the interview stops being a form and starts being an
# interpretation.  Individual answers add broad subjects; *combinations* of
# answers reveal a specific sensibility that no single answer names.  Each combo
# below fires only when all of its tags are present, and injects an emergent
# thread — weighted more heavily than the raw answers, because a coincidence of
# signals is a stronger signal than any one of them alone.

@dataclass
class Combo:
    when: frozenset
    label: str  # shown back to the reader
    subjects: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    tune: Dict[str, float] = field(default_factory=dict)


COMBOS: List[Combo] = [
    Combo(
        frozenset({"cave", "deep"}),
        "an obsessive descent into a single subject",
        subjects=["speleology", "monograph", "the unknown", "obsession"],
        keywords=["a single obsessive descent", "going deeper"],
    ),
    Combo(
        frozenset({"static", "rumor"}),
        "paranoid, fragmentary, conspiratorial",
        subjects=["conspiracy", "experimental fiction", "paranoia", "secret history"],
        keywords=["cut-up", "signal and noise"],
        tune={"adventurousness": 0.1},
    ),
    Combo(
        frozenset({"ghost", "moss"}),
        "hauntology — landscape that remembers",
        subjects=["hauntology", "landscape", "ghost stories", "memory", "ruins"],
        keywords=["the persistence of place", "overgrown"],
    ),
    Combo(
        frozenset({"window", "unreliable"}),
        "voyeuristic domestic unease",
        subjects=["domestic fiction", "surveillance", "psychological fiction",
                  "loneliness"],
        keywords=["watching the neighbours", "what the walls hide"],
    ),
    Combo(
        frozenset({"glass", "given-up"}),
        "cold, clinical existential modernism",
        subjects=["modernism", "existentialism", "alienation", "detachment"],
        keywords=["clinical despair"],
    ),
    Combo(
        frozenset({"tree-door", "ghost"}),
        "folk horror / the uncanny pastoral",
        subjects=["folk horror", "the uncanny", "folklore", "the gothic"],
        keywords=["old ways", "something in the wood"],
        tune={"adventurousness": 0.1},
    ),
    Combo(
        frozenset({"gravel", "scar"}),
        "hard-bitten witness realism",
        subjects=["realism", "war", "working class", "testimony"],
        keywords=["plainspoken grief"],
    ),
    Combo(
        frozenset({"burning-library", "deep"}),
        "the scholar's obsession — bibliomania",
        subjects=["bibliomania", "essays", "obsession", "memory"],
        keywords=["marginalia", "the one book"],
    ),
    Combo(
        frozenset({"joke", "given-up"}),
        "gallows humour / comic despair",
        subjects=["dark comedy", "satire", "existentialism", "the absurd"],
        keywords=["laughing at the void"],
    ),
    Combo(
        frozenset({"map", "broad"}),
        "the systems-thinking polymath sweep",
        subjects=["systems", "science", "encyclopedic fiction", "history of ideas"],
        keywords=["how everything connects"],
    ),
    Combo(
        frozenset({"cave", "ghost"}),
        "the buried past — a descent into memory",
        subjects=["the unknown", "memory", "the gothic", "archaeology"],
        keywords=["what is buried"],
    ),
    Combo(
        frozenset({"rumor", "ancient"}),
        "heretical and secret histories",
        subjects=["secret history", "occult", "antiquity", "apocrypha"],
        keywords=["suppressed texts"],
    ),
    Combo(
        frozenset({"map", "static"}),
        "order dissolving into noise",
        subjects=["entropy", "systems", "experimental fiction", "information"],
        keywords=["the map coming apart"],
    ),
    Combo(
        frozenset({"window", "noticer"}),
        "the poetry of the overlooked ordinary",
        subjects=["everyday life", "phenomenology", "domestic fiction", "attention"],
        keywords=["the miraculous mundane"],
    ),
]


def synthesize(profile: TasteProfile) -> TasteProfile:
    """Fold combination rules into the profile.  Emergent threads are weighted
    above raw answers because a coincidence of signals is the stronger signal."""
    for combo in COMBOS:
        if combo.when <= profile.signals:
            for subject in combo.subjects:
                profile.add_subject(subject, weight=1.4)
            for kw in combo.keywords:
                profile.add_keyword(kw)
            profile.blend(combo.tune)
            profile.emergent.append(combo.label)
    return profile


def run_interactive(inp=input, out=print) -> TasteProfile:
    """Conduct the full interview at a terminal and return a profile."""
    profile = TasteProfile()
    out("")
    out("  Answer honestly or answer strangely — both work.")
    out("  Press Enter alone to skip a question.\n")
    for q in QUESTIONS:
        out(q.prompt)
        if q.freeform is not None:
            raw = inp("  > ").strip()
            if raw:
                q.freeform(profile, raw)
            out("")
            continue
        for i, opt in enumerate(q.options, 1):
            out(f"    {i}. {opt.label}")
        raw = inp("  > ").strip()
        out("")
        _apply_choice(profile, q, raw)
    return synthesize(profile)


def _apply_choice(profile: TasteProfile, q: Question, raw: str) -> None:
    if not raw:
        return
    try:
        idx = int(raw) - 1
    except ValueError:
        # Treat a typed word as free keyword input — never punish the reader.
        profile.add_keyword(raw)
        profile.add_subject(raw, weight=0.5)
        return
    if 0 <= idx < len(q.options):
        _apply_option(profile, q.options[idx])


def _apply_option(profile: TasteProfile, opt: Option) -> None:
    # Earlier subjects in the list weigh more heavily.
    for rank, subject in enumerate(opt.subjects):
        profile.add_subject(subject, weight=max(0.4, 1.0 - 0.15 * rank))
    for kw in opt.keywords:
        profile.add_keyword(kw)
    profile.moods.append(opt.label)
    if opt.tag:
        profile.signals.add(opt.tag)
    for attr, value in opt.sets.items():
        setattr(profile, attr, value)
    profile.blend(opt.tune)


def quick_profile(answers: Dict[str, str]) -> TasteProfile:
    """Build a profile from ``{question_key: answer}`` without prompting.

    ``answer`` may be a 1-based option number or free text.  Used by the
    ``--answer key=value`` CLI flags and by the test-suite.
    """
    profile = TasteProfile()
    by_key = {q.key: q for q in QUESTIONS}
    for key, val in answers.items():
        q = by_key.get(key)
        if q is None:
            continue
        if q.freeform is not None:
            q.freeform(profile, val)
        else:
            _apply_choice(profile, q, val)
    return synthesize(profile)
