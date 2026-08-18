"""Verification checks: inversion continuity, drift detection, equivalence.

The checks here are the "look-ahead freedom as a verifiable property" core
of pit-adjuster.  They operate on the value-independent fragment of the
adjustment problem (factor chains, ex-date ordering, chain inversion) where
the checks are exact; the general value-dependent case falls back to
heuristic guards, stated explicitly per check.
"""

from __future__ import annotations

import bisect
import math
from typing import Any

from .chain import _bar_date, _raw_close, events_from_actions


def validate_inversion(
    bars: list[dict[str, Any]],
    events: list[dict[str, Any]],
    *,
    as_of_date: str,
    tolerance: float = 0.03,
) -> list[dict[str, Any]]:
    """Sanity check of ex-date continuity on rebuilt (raw_close) bars.

    Theoretical raw price on the ex-date is ``raw_{ex-1} * factor_e`` (the
    exchange ex-right reference price).  This is informational: with real
    data the ex-date itself carries a normal overnight return, so violations
    can be false positives.  The authoritative divergence check is
    ``compare_raw_closes`` against live raw closes.
    """
    events = events_from_actions(events, as_of_date=as_of_date)
    if not events:
        return []
    violations: list[dict[str, Any]] = []
    by_date: dict[str, dict[str, Any]] = {}
    for bar in bars:
        date_text = _bar_date(bar)
        if date_text:
            by_date[date_text] = bar
    dates = sorted(by_date)
    for event in events:
        ex_date = event["ex_date"]
        index = bisect.bisect_left(dates, ex_date)
        if index <= 0 or index >= len(dates):
            continue
        prev_date = dates[index - 1]
        cur_date = dates[index]
        prev_raw = _raw_close(by_date[prev_date])
        cur_raw = _raw_close(by_date[cur_date])
        if prev_raw is None or cur_raw is None or prev_raw <= 0:
            continue
        expected = prev_raw * float(event["factor"])
        deviation = abs(cur_raw - expected) / expected
        if deviation > tolerance:
            violations.append(
                {
                    "ex_date": ex_date,
                    "first_bar_on_or_after": cur_date,
                    "factor": float(event["factor"]),
                    "prev_date": prev_date,
                    "prev_raw_close": prev_raw,
                    "raw_close": cur_raw,
                    "expected_raw_close": round(expected, 6),
                    "deviation": round(deviation, 6),
                    "tolerance": tolerance,
                }
            )
    return violations


def compare_raw_closes(
    bars: list[dict[str, Any]],
    live_closes: dict[str, float],
    *,
    sample_days: int = 5,
) -> dict[str, Any]:
    """Compare inverted raw closes against live raw closes.

    Directly detects vendor qfq chains that diverge from the archive
    adjustment factors (deviation above tolerance is authoritative).  This
    is the **static forward-adjustment detector**: if a vendor silently
    swaps adjustment conventions, inverted raws stop matching live raws and
    this check fires.
    """
    dated = [bar for bar in bars if bar.get("date") and bar.get("raw_close")]
    dated.sort(key=lambda bar: str(bar["date"]))
    sampled = dated[-max(1, sample_days):]
    rows: list[dict[str, Any]] = []
    for bar in sampled:
        day = str(bar["date"])[:10]
        live = live_closes.get(day)
        try:
            live_f = float(live)
        except (TypeError, ValueError):
            continue
        inverted = float(bar["raw_close"])
        if not math.isfinite(live_f) or live_f <= 0 or not math.isfinite(inverted):
            continue
        deviation = abs(inverted - live_f) / live_f
        rows.append(
            {
                "date": day,
                "inverted": round(inverted, 6),
                "live": live_f,
                "deviation": round(deviation, 6),
            }
        )
    worst = max((row["deviation"] for row in rows), default=None)
    return {"checked": len(rows), "worst_deviation": worst, "rows": rows}


def compare_snapshots(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    *,
    tolerance: float = 1e-6,
) -> dict[str, Any]:
    """Compare two rebuilt outputs date-by-date (equivalence gate).

    Used to prove that a pipeline migration, archive refresh or parameter
    change did not silently alter history.  Compares ``close`` and
    ``adj_factor`` per date; rows missing from either side are reported.
    Returns ``{"equal": bool, "checked": int, "differences": [...], "missing": [...]}``.
    """
    def _index(bars: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for bar in bars:
            date_text = str(bar.get("date") or "")[:10]
            if date_text:
                out[date_text] = bar
        return out

    before_map = _index(before)
    after_map = _index(after)
    differences: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for date_text in sorted(set(before_map) | set(after_map)):
        before_bar = before_map.get(date_text)
        after_bar = after_map.get(date_text)
        if before_bar is None or after_bar is None:
            missing.append(
                {
                    "date": date_text,
                    "present_in_before": before_bar is not None,
                    "present_in_after": after_bar is not None,
                }
            )
            continue
        for key in ("close", "adj_factor"):
            before_value = before_bar.get(key)
            after_value = after_bar.get(key)
            try:
                before_f = float(before_value)
                after_f = float(after_value)
            except (TypeError, ValueError):
                continue
            if not (math.isfinite(before_f) and math.isfinite(after_f)):
                continue
            deviation = abs(before_f - after_f) / max(abs(after_f), 1e-12)
            if deviation > tolerance:
                differences.append(
                    {
                        "date": date_text,
                        "field": key,
                        "before": before_value,
                        "after": after_value,
                        "deviation": round(deviation, 12),
                    }
                )
    return {
        "equal": not differences and not missing,
        "checked": len(before_map),
        "differences": differences,
        "missing": missing,
    }
