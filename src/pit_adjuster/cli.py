"""Command-line interface for pit-adjuster.

Subcommands:

- ``rebuild``                rebuild bars to fixed-basis hfq (PIT)
- ``invert-check``           ex-date continuity sanity check
- ``drift-check``            static forward-adjustment detection vs live closes
- ``snapshot-equivalence``   before/after equivalence of two rebuilds
- ``version``                print version
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import __version__
from .chain import events_from_actions, rebuild_bars
from .io import load_actions, load_bars, write_json
from .validation import compare_raw_closes, compare_snapshots, validate_inversion


def _print_summary(heading: str, body: dict[str, Any]) -> None:
    print(f"== {heading} ==")
    print(json.dumps(body, ensure_ascii=False, indent=2))


def _add_common_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bars", required=True, help="bars JSON/JSONL path")
    parser.add_argument("--actions", required=True, help="corporate-action archive JSON/JSONL path")
    parser.add_argument("--as-of", required=True, help="PIT cutoff date (YYYY-MM-DD)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="padj",
        description="Point-in-time fixed-basis back-adjustment engine.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    rebuild = sub.add_parser("rebuild", help="rebuild bars to fixed-basis hfq (PIT)")
    _add_common_inputs(rebuild)
    rebuild.add_argument("--code", default=None, help="instrument code (prefix rules for volume)")
    rebuild.add_argument("--volume-to-shares", type=float, default=None, help="override volume multiplier")
    rebuild.add_argument("--out", default=None, help="output path (JSON); default: stdout summary")

    invert = sub.add_parser("invert-check", help="ex-date continuity sanity check")
    _add_common_inputs(invert)
    invert.add_argument("--tolerance", type=float, default=0.03)

    drift = sub.add_parser("drift-check", help="static forward-adjustment detection vs live closes")
    _add_common_inputs(drift)
    drift.add_argument("--live", required=True, help="live raw closes JSON (date -> close)")
    drift.add_argument("--sample-days", type=int, default=5)

    snap = sub.add_parser("snapshot-equivalence", help="before/after equivalence of two rebuilds")
    snap.add_argument("--before", required=True, help="rebuilt bars JSON (old pipeline)")
    snap.add_argument("--after", required=True, help="rebuilt bars JSON (new pipeline)")
    snap.add_argument("--tolerance", type=float, default=1e-6)

    sub.add_parser("version", help="print version")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "version":
        print(__version__)
        return 0

    if args.command == "rebuild":
        bars = load_bars(args.bars)
        actions = load_actions(args.actions)
        new_bars, stats = rebuild_bars(
            bars,
            actions,
            as_of_date=args.as_of,
            code=args.code,
            volume_to_shares=args.volume_to_shares,
        )
        if args.out:
            write_json(args.out, new_bars)
            print(f"rebuild: {stats['bars']} bars, {stats['invalid_bars']} invalid -> {args.out}")
        else:
            _print_summary(f"rebuild ({stats['bars']} bars, {stats['invalid_bars']} invalid)", new_bars[-5:])
        return 0

    if args.command == "invert-check":
        bars = load_bars(args.bars)
        actions = load_actions(args.actions)
        violations = validate_inversion(bars, actions, as_of_date=args.as_of, tolerance=args.tolerance)
        if violations:
            _print_summary(f"invert-check: {len(violations)} violation(s)", {"violations": violations})
            return 1
        print("invert-check: ok (no ex-date continuity violations)")
        return 0

    if args.command == "drift-check":
        bars = load_bars(args.bars)
        actions = load_actions(args.actions)
        live = _load_live(args.live)
        report = compare_raw_closes(bars, live, sample_days=args.sample_days)
        _print_summary("drift-check", report)
        if report["worst_deviation"] is not None and report["worst_deviation"] > 0.01:
            return 1
        return 0

    if args.command == "snapshot-equivalence":
        before = load_bars(args.before)
        after = load_bars(args.after)
        report = compare_snapshots(before, after, tolerance=args.tolerance)
        _print_summary("snapshot-equivalence", report)
        return 0 if report["equal"] else 1

    parser.error(f"unknown command: {args.command}")
    return 2


def _load_live(path: str) -> dict[str, float]:
    import os

    if path.endswith(".jsonl"):
        rows: dict[str, float] = {}
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if isinstance(row, dict) and row.get("date"):
                    rows[str(row["date"])[:10]] = float(row["close"])
        return rows
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            return {str(key)[:10]: float(value) for key, value in loaded.items()}
    raise ValueError(f"live closes must be a JSON object mapping date -> close: {path}")


if __name__ == "__main__":
    sys.exit(main())
