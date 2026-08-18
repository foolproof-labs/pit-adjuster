"""Unit tests for the verification checks (inversion, drift, equivalence)."""

from __future__ import annotations

from pit_adjuster.chain import rebuild_bars
from pit_adjuster.validation import (
    compare_raw_closes,
    compare_snapshots,
    validate_inversion,
)


def _bar(date: str, close: float, open_: float | None = None, volume: float = 1000.0) -> dict:
    value = open_ if open_ is not None else close
    return {
        "date": date,
        "open": value,
        "high": value,
        "low": value,
        "close": close,
        "volume": volume,
        "amount": close * volume,
        "turnover": 1.0,
        "source": "test",
    }


def _action(ex_date: str, factor: float) -> dict:
    return {
        "action_id": f"test-{ex_date}",
        "action_type": "cash_dividend_stock_distribution",
        "ex_date": ex_date,
        "available_at": ex_date,
        "adjustment_factor": factor,
    }


def test_validation_flags_large_ex_date_jump() -> None:
    """Continuity sanity check flags an implausible raw jump at ex-date."""
    actions = [_action("2026-06-15", 0.95)]
    bars = [_bar("2026-06-12", 100.0), _bar("2026-06-15", 110.0)]
    rebuilt, _ = rebuild_bars(bars, actions, as_of_date="2026-08-11")
    violations = validate_inversion(rebuilt, actions, as_of_date="2026-08-11", tolerance=0.05)
    assert len(violations) == 1
    assert violations[0]["deviation"] > 0.05


def test_validation_handles_missing_ex_date_bar() -> None:
    """Ex-date falling on a non-trading day uses the first bar after it."""
    actions = [_action("2026-06-14", 0.95)]  # Sunday in this synthetic series
    bars = [_bar("2026-06-12", 100.0), _bar("2026-06-15", 95.5)]
    rebuilt, _ = rebuild_bars(bars, actions, as_of_date="2026-08-11")
    violations = validate_inversion(rebuilt, actions, as_of_date="2026-08-11", tolerance=0.05)
    assert violations == []  # 95.5 vs 100*0.95=95 -> within tolerance


def test_compare_raw_closes_catches_vendor_divergence() -> None:
    """Inverted raws that differ from live closes are flagged authoritatively."""
    actions = [_action("2026-06-15", 0.95)]
    # vendor used factor 0.99, so inverted raw differs from the live raw.
    qfq_bars = [
        _bar("2026-06-12", 100.0 * 0.99),
        _bar("2026-06-15", 99.0),
    ]
    rebuilt, _ = rebuild_bars(qfq_bars, actions, as_of_date="2026-08-11")
    live = {"2026-06-12": 100.0, "2026-06-15": 99.0}
    report = compare_raw_closes(rebuilt, live, sample_days=5)
    assert report["checked"] == 2
    assert report["worst_deviation"] is not None
    assert report["worst_deviation"] > 0.01  # 100*0.99/0.95 vs 100


def test_compare_raw_closes_exact_match() -> None:
    actions = [_action("2026-06-15", 0.95)]
    qfq_bars = [
        _bar("2026-06-12", 100.0 * 0.95),
        _bar("2026-06-15", 99.0),
    ]
    rebuilt, _ = rebuild_bars(qfq_bars, actions, as_of_date="2026-08-11")
    live = {"2026-06-12": 100.0, "2026-06-15": 99.0}
    report = compare_raw_closes(rebuilt, live, sample_days=5)
    assert report["worst_deviation"] < 1e-6


def test_snapshot_equivalence_identical() -> None:
    actions = [_action("2026-06-15", 0.95)]
    qfq_bars = [_bar("2026-06-12", 100.0 * 0.95), _bar("2026-06-15", 99.0)]
    rebuilt, _ = rebuild_bars(qfq_bars, actions, as_of_date="2026-08-11")
    report = compare_snapshots(rebuilt, rebuilt)
    assert report["equal"] is True
    assert report["checked"] == 2
    assert report["differences"] == []
    assert report["missing"] == []


def test_snapshot_equivalence_detects_change() -> None:
    actions = [_action("2026-06-15", 0.95)]
    qfq_bars = [_bar("2026-06-12", 100.0 * 0.95), _bar("2026-06-15", 99.0)]
    rebuilt, _ = rebuild_bars(qfq_bars, actions, as_of_date="2026-08-11")
    tampered = [dict(bar) for bar in rebuilt]
    tampered[0]["close"] = round(tampered[0]["close"] * 1.02, 6)
    report = compare_snapshots(rebuilt, tampered)
    assert report["equal"] is False
    assert any(diff["date"] == "2026-06-12" for diff in report["differences"])


def test_snapshot_equivalence_reports_missing_dates() -> None:
    actions = [_action("2026-06-15", 0.95)]
    qfq_bars = [_bar("2026-06-12", 100.0 * 0.95), _bar("2026-06-15", 99.0)]
    rebuilt, _ = rebuild_bars(qfq_bars, actions, as_of_date="2026-08-11")
    truncated = rebuilt[:-1]
    report = compare_snapshots(rebuilt, truncated)
    assert report["equal"] is False
    assert any(row["date"] == "2026-06-15" for row in report["missing"])
