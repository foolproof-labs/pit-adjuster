"""Core adjustment chain: PIT-safe fixed-basis back-adjusted (hfq) prices.

Builds a PIT-safe daily history from:

- current-vintage forward-adjusted (qfq) daily bars, and
- a point-in-time corporate-action archive (one ``adjustment_factor`` per
  event).

Standard A-share adjustment math (exchange reference-price convention):

    factor_e = (prior_close - cash) / (prior_close * (1 + bonus + transfer))
    qfq_t    = raw_t * prod_{e: ex_date_e > t} factor_e
    hfq_t    = raw_t * prod_{e: ex_date_e <= t} (1 / factor_e)

The rebuild inverts the vendor qfq chain back to raw prices, then re-applies
only events whose ex-date is on or before each bar date (fixed basis at the
archive coverage start). Raw open/close are kept alongside so
execution-level backtests can map adjusted prices back to nominal prices.
"""

from __future__ import annotations

import bisect
import math
from typing import Any

DEFAULT_VOLUME_TO_SHARES = 100.0
DEFAULT_NATIVE_SHARE_PREFIXES = ("688", "689")


def events_from_actions(
    actions: list[dict[str, Any]], *, as_of_date: str
) -> list[dict[str, Any]]:
    """Return actions sorted by ex-date, keeping only events <= as_of_date.

    Each returned event carries ``ex_date``, ``factor`` and ``available_at``.
    Invalid records (missing ex-date or non-positive factor) are dropped.
    """
    events: list[dict[str, Any]] = []
    for action in actions or []:
        ex_date = str(action.get("ex_date") or "")
        factor = action.get("adjustment_factor")
        try:
            factor = float(factor)
        except (TypeError, ValueError):
            continue
        if len(ex_date) < 10 or not math.isfinite(factor) or factor <= 0:
            continue
        if ex_date[:10] > as_of_date:
            continue
        events.append(
            {
                "ex_date": ex_date[:10],
                "factor": factor,
                "available_at": str(action.get("available_at") or ""),
            }
        )
    events.sort(key=lambda item: item["ex_date"])
    return events


def build_multipliers(
    events: list[dict[str, Any]],
) -> tuple[list[str], list[float], list[float]]:
    """Return ``(ex_dates, hfq_prefix, qfq_suffix)`` cumulative multipliers.

    ``hfq_prefix[k]`` = prod_{j<k} (1 / factor_j)
    ``qfq_suffix[k]`` = prod_{j>=k} factor_j
    Both arrays have length ``n + 1``; ``k`` is the count of events whose
    ex-date is on or before a bar date (0 .. n).
    """
    ex_dates = [event["ex_date"] for event in events]
    count = len(events)
    hfq_prefix = [1.0] * (count + 1)
    acc = 1.0
    for index, event in enumerate(events):
        acc *= 1.0 / float(event["factor"])
        hfq_prefix[index + 1] = acc
    qfq_suffix = [1.0] * (count + 1)
    acc = 1.0
    for index in range(count - 1, -1, -1):
        acc *= float(events[index]["factor"])
        qfq_suffix[index] = acc
    return ex_dates, hfq_prefix, qfq_suffix


def _bar_date(bar: dict[str, Any]) -> str:
    return str(bar.get("date") or "")[:10]


def _raw_close(bar: dict[str, Any]) -> float | None:
    value = bar.get("raw_close")
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def rebuild_bars(
    bars: list[dict[str, Any]],
    events: list[dict[str, Any]],
    *,
    as_of_date: str,
    code: str | None = None,
    volume_to_shares: float | None = None,
    native_share_prefixes: tuple[str, ...] = DEFAULT_NATIVE_SHARE_PREFIXES,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Rebuild one code's bars to fixed-basis hfq (PIT).

    Returns ``(new_bars, stats)``.  Every valid bar gets ``open/high/low/
    close`` as hfq prices, ``raw_open/raw_close`` as nominal prices, and
    ``adj_factor`` as the cumulative hfq multiplier.  Volume is converted to
    shares: codes whose prefix is in ``native_share_prefixes`` already store
    shares (no conversion), all other codes use ``volume_to_shares``
    (default: 1 lot = 100 shares).  Amount, turnover and any extra fields
    are preserved.

    The PIT property: a price at time ``t`` is a function only of events
    whose ex-date is on or before ``t`` (fixed basis at archive coverage
    start).
    """
    effective_multiplier = (
        volume_to_shares
        if volume_to_shares is not None
        else (
            1.0
            if str(code or "").startswith(native_share_prefixes)
            else DEFAULT_VOLUME_TO_SHARES
        )
    )
    events = events_from_actions(events, as_of_date=as_of_date)
    ex_dates, hfq_prefix, qfq_suffix = build_multipliers(events)
    new_bars: list[dict[str, Any]] = []
    stats: dict[str, int] = {"bars": 0, "invalid_bars": 0}
    for bar in bars or []:
        date_text = _bar_date(bar)
        if not date_text:
            stats["invalid_bars"] += 1
            continue
        close = bar.get("close")
        try:
            close_f = float(close)
        except (TypeError, ValueError):
            close_f = math.nan
        valid = math.isfinite(close_f) and close_f > 0
        k = bisect.bisect_right(ex_dates, date_text) if ex_dates else 0
        qfq_mult = qfq_suffix[k] if ex_dates else 1.0
        hfq_mult = hfq_prefix[k] if ex_dates else 1.0
        rebuilt = dict(bar)
        try:
            volume_f = float(bar.get("volume") or 0.0)
        except (TypeError, ValueError):
            volume_f = math.nan
        if math.isfinite(volume_f) and volume_f > 0:
            rebuilt["volume"] = round(volume_f * effective_multiplier, 2)
        else:
            rebuilt["volume"] = volume_f if math.isfinite(volume_f) else None
        if valid:
            raw_close = close_f / qfq_mult
            rebuilt["raw_close"] = round(raw_close, 6)
            rebuilt["adj_factor"] = round(hfq_mult, 12)
            for key in ("open", "high", "low"):
                value = bar.get(key)
                try:
                    value_f = float(value)
                except (TypeError, ValueError):
                    value_f = math.nan
                if math.isfinite(value_f) and value_f > 0:
                    raw_value = value_f / qfq_mult
                    rebuilt[key] = round(raw_value * hfq_mult, 6)
                    if key == "open":
                        rebuilt["raw_open"] = round(raw_value, 6)
                else:
                    rebuilt[key] = None
            rebuilt["close"] = round(raw_close * hfq_mult, 6)
            stats["bars"] += 1
        else:
            rebuilt["raw_close"] = None
            rebuilt["raw_open"] = None
            rebuilt["adj_factor"] = 1.0
            stats["invalid_bars"] += 1
        new_bars.append(rebuilt)
    return new_bars, stats
