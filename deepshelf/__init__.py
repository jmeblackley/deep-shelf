"""Deepshelf — book recommendations from the deep shelves.

A recommender that deliberately weighs *against* popularity and recency, draws
from open catalogues (Open Library / Internet Archive) plus a hand-curated
corpus of deep cuts, and probes taste through oblique, creative questions.
"""

__version__ = "1.0.0"

from .profile import TasteProfile  # noqa: E402,F401
from .recommender import recommend  # noqa: E402,F401
