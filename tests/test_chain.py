"""Unit tests for the PIT fixed-basis hfq adjustment chain."""

from __future__ import annotations

from pit_adjuster.chain import (
    build_multipliers,
    events_from_actions,
    rebuild_bars,
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


def _action(ex_date: str, factor: float, available_at: str | None = None) -> dict:
    return {
        "action_id": f"test-{ex_date}",
        "action_type": "cash_dividend_stock_distribution",
        "ex_date": ex_date,
        "available_at": available_at or ex_date,
        "adjustment_factor": factor,
    }


def test_events_filter_and_sort() -> None:
    actions = [
        _action("2026-06-15", 0.997),
        _action("2024-06-17", 0.96),
        _action("2027-01-01", 0.99),  # after as_of -> dropped
    ]
    events = events_from_actions(actions, as_of_date="2026-08-11")
    assert [event["ex_date"] for event in events] == ["2024-06-17", "2026-06-15"]


def test_events_drop_invalid_records() -> None:
    actions = [
        {"ex_date": "2026-06-15", "adjustment_factor": "not-a-number"},
        {"ex_date": "", "adjustment_factor": 0.99},
        {"ex_date": "2026-06-15", "adjustment_factor": -1.0},
        _action("2026-06-15", 0.99),
    ]
    events = events_from_actions(actions, as_of_date="2026-08-11")
    assert len(events) == 1


def test_qfq_to_hfq_roundtrip() -> None:
    """qfq prices inverted to raw, then rebuilt to hfq, keep returns intact."""
    actions = [
        _action("2025-06-10", 0.95),
        _action("2026-06-15", 0.99),
    ]
    normalized = events_from_actions(actions, as_of_date="2026-08-11")
    ex_dates, hfq_prefix, qfq_suffix = build_multipliers(normalized)
    assert abs(qfq_suffix[0] - (0.95 * 0.99)) < 1e-12
    assert abs(qfq_suffix[1] - 0.99) < 1e-12
    assert abs(qfq_suffix[2] - 1.0) < 1e-12
    assert abs(hfq_prefix[0] - 1.0) < 1e-12
    assert abs(hfq_prefix[1] - (1 / 0.95)) < 1e-12
    assert abs(hfq_prefix[2] - (1 / 0.95 / 0.99)) < 1e-12

    raw_prices = [100.0, 101.0, 60.0, 61.0]  # daily prices
    dates = ["2025-06-09", "2025-06-10", "2026-06-14", "2026-06-15"]
    qfq_bars = []
    for day, raw in zip(dates, raw_prices):
        k = sum(1 for e in normalized if e["ex_date"] > day)
        qfq_close = raw * (0.95 * 0.99 if k == 2 else 0.99 if k == 1 else 1.0)
        qfq_bars.append(_bar(day, round(qfq_close, 6)))

    new_bars, stats = rebuild_bars(qfq_bars, actions, as_of_date="2026-08-11")
    assert stats["bars"] == 4
    assert new_bars[0]["volume"] == 1000.0 * 100.0  # lots -> shares
    assert abs(new_bars[0]["raw_close"] - raw_prices[0]) < 1e-4
    assert abs(new_bars[3]["raw_close"] - raw_prices[3]) < 1e-4
    assert abs(new_bars[3]["adj_factor"] - (1 / 0.95 / 0.99)) < 1e-9
    assert abs(new_bars[0]["adj_factor"] - 1.0) < 1e-9

    # hfq and qfq must yield identical adjusted returns (same factor chain).
    hfq_ret = new_bars[1]["close"] / new_bars[0]["close"] - 1
    qfq_ret = qfq_bars[1]["close"] / qfq_bars[0]["close"] - 1
    assert abs(hfq_ret - qfq_ret) < 1e-6  # 6-decimal rounding tolerance


def test_pit_property() -> None:
    """hfq price at t is unaffected by events whose ex-date is after t."""
    actions = [_action("2026-06-15", 0.99)]
    # qfq inputs: raw 100/101/99 with a pending 0.99 factor before the ex-date.
    bars = [
        _bar("2026-01-05", 100.0 * 0.99),
        _bar("2026-06-14", 101.0 * 0.99),
        _bar("2026-06-15", 99.0),
    ]
    new_bars, _ = rebuild_bars(bars, actions, as_of_date="2026-08-11")
    assert new_bars[0]["close"] == 100.0  # event after this date must not touch it
    assert new_bars[1]["close"] == 101.0
    assert abs(new_bars[2]["close"] - 99.0 / 0.99) < 1e-6


def test_invalid_bars_preserved() -> None:
    events = [{"ex_date": "2026-06-15", "factor": 0.99}]
    bars = [_bar("2026-01-05", 100.0), {"date": "2026-06-14", "close": 0.0, "open": 0.0}]
    new_bars, stats = rebuild_bars(bars, events, as_of_date="2026-08-11")
    assert stats["invalid_bars"] == 1
    assert new_bars[1]["raw_close"] is None
    assert new_bars[1]["adj_factor"] == 1.0


def test_star_market_volume_is_native_shares() -> None:
    """688/689 volume is already shares; no 100x conversion applies."""
    bars = [_bar("2026-06-01", 47.0, volume=1500000.0)]
    new_bars, _ = rebuild_bars(bars, [], as_of_date="2026-08-11", code="688001")
    assert new_bars[0]["volume"] == 1500000.0
    main_bars, _ = rebuild_bars(bars, [], as_of_date="2026-08-11", code="600000")
    assert main_bars[0]["volume"] == 1500000.0 * 100.0


def test_custom_native_share_prefixes() -> None:
    """The native-share prefix set is parameterizable."""
    bars = [_bar("2026-06-01", 47.0, volume=1500000.0)]
    custom, _ = rebuild_bars(
        bars, [], as_of_date="2026-08-11", code="600000", native_share_prefixes=("600",)
    )
    assert custom[0]["volume"] == 1500000.0


def test_bars_without_events_are_passthrough() -> None:
    bars = [_bar("2026-06-01", 47.0, volume=100.0)]
    new_bars, stats = rebuild_bars(bars, [], as_of_date="2026-08-11")
    assert stats["bars"] == 1
    assert new_bars[0]["close"] == 47.0
    assert new_bars[0]["adj_factor"] == 1.0
    assert new_bars[0]["raw_close"] == 47.0
