"""pit-adjuster: point-in-time fixed-basis back-adjustment engine.

Rebuild daily price history so that any day reads exactly what that day
could have known: fixed-basis hfq prices from current-vintage qfq bars plus
a point-in-time corporate-action archive, with verifiable inversion,
forward-adjustment drift detection and snapshot equivalence checks.

Zero dependencies. Python 3.11+.
"""

from .chain import build_multipliers, events_from_actions, rebuild_bars
from .validation import compare_raw_closes, compare_snapshots, validate_inversion

__version__ = "0.1.1"

__all__ = [
    "build_multipliers",
    "compare_raw_closes",
    "compare_snapshots",
    "events_from_actions",
    "rebuild_bars",
    "validate_inversion",
]

