"""End-to-end demo on synthetic data: rebuild -> invert-check -> drift-check.

Run with:  python examples/demo.py
No network, no third-party dependencies. Builds a small fake history for a
single code, rebuils it to fixed-basis hfq, then runs every verification
check. A drift scenario (vendor silently swapped conventions) is simulated
at the end so you can see drift-check fire.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pit_adjuster.chain import rebuild_bars  # noqa: E402
from pit_adjuster.validation import (  # noqa: E402
    compare_raw_closes,
    compare_snapshots,
    validate_inversion,
)

AS_OF = "2026-08-11"

# --- synthetic history ------------------------------------------------------
# Raw daily closes for a code that pays two distributions.
RAW_PRICES = [100.0, 101.0, 60.0, 61.0, 62.0, 63.0]
DATES = ["2026-05-08", "2026-05-09", "2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18"]
FACTORS = [("2026-05-09", 0.95), ("2026-06-15", 0.99)]  # (ex_date, factor)

ACTIONS = [
    {
        "action_id": f"demo-{ex_date}",
        "action_type": "cash_dividend_stock_distribution",
        "ex_date": ex_date,
        "available_at": f"{ex_date}T18:00:00",
        "adjustment_factor": factor,
    }
    for ex_date, factor in FACTORS
]


def _build_qfq_bars() -> list[dict]:
    """Current-vintage qfq bars: raw price times all pending factors."""
    bars = []
    for day, raw in zip(DATES, RAW_PRICES):
        pending = [factor for ex_date, factor in FACTORS if ex_date > day]
        mult = 1.0
        for factor in pending:
            mult *= factor
        qfq_close = round(raw * mult, 6)
        bars.append(
            {
                "date": day,
                "open": qfq_close,
                "high": qfq_close,
                "low": qfq_close,
                "close": qfq_close,
                "volume": 1200.0,  # lots; 600000-style code -> x100 to shares
                "amount": round(qfq_close * 1200.0, 2),
                "turnover": 1.0,
            }
        )
    return bars


def _print(label: str, body) -> None:
    import json

    print(f"\n== {label} ==")
    print(json.dumps(body, ensure_ascii=False, indent=2))


def main() -> int:
    qfq = _build_qfq_bars()
    _print("1. vendor qfq bars (current vintage)", qfq)

    rebuilt, stats = rebuild_bars(qfq, ACTIONS, as_of_date=AS_OF, code="600000")
    _print(f"2. rebuilt to fixed-basis hfq ({stats['bars']} bars, {stats['invalid_bars']} invalid)", rebuilt)

    violations = validate_inversion(rebuilt, ACTIONS, as_of_date=AS_OF)
    _print("3. invert-check (ex-date continuity)", {"violations": len(violations)})

    live = {day: raw for day, raw in zip(DATES, RAW_PRICES)}
    report = compare_raw_closes(rebuilt, live)
    _print("4. drift-check vs live raw closes (clean)", report)

    same = compare_snapshots(rebuilt, [dict(bar) for bar in rebuilt])
    _print("5. snapshot-equivalence (identical rebuild)", same)

    # --- drift scenario: archive corrected, vendor chain not rebuilt ---------
    # A corporate action's factor gets corrected from 0.99 to 0.94 in the
    # archive, but the vendor's qfq chain was built from the old 0.99. Every
    # bar BEFORE the ex-date now inverts to a raw price ~5% off live.
    corrected_actions = [
        {
            "action_id": f"demo-{ex_date}",
            "action_type": "cash_dividend_stock_distribution",
            "ex_date": ex_date,
            "available_at": f"{ex_date}T18:00:00",
            "adjustment_factor": factor,
        }
        for ex_date, factor in [("2026-05-09", 0.95), ("2026-06-15", 0.94)]
    ]
    rebuilt_drift, _ = rebuild_bars(qfq, corrected_actions, as_of_date=AS_OF, code="600000")
    drift = compare_raw_closes(rebuilt_drift, live)
    _print("6. drift-check (archive corrected 0.99 -> 0.94; stale vendor chain -> should fire)", drift)

    fired = drift["worst_deviation"] is not None and drift["worst_deviation"] > 0.01
    print("\n=> static forward-adjustment detection:", "FIRED (vendor drift caught)" if fired else "clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
