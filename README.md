# pit-adjuster

## 中文说明

`pit-adjuster` 面向 A 股等股票市场的历史行情复权和公司行为数据处理。
它根据带时间点的公司行为档案重建固定基准价格，检查复权因子链是否连续，
并识别数据供应商悄悄切换复权口径的情况。工具只处理和验证历史数据，
不预测价格、不提供交易建议；公司行为的发生日、公告时间和数据覆盖范围
必须由使用者提供并核验。

Point-in-time fixed-basis back-adjustment engine for daily price history:
rebuild prices so that **any day reads exactly what that day could have
known** —plus drift detection for vendors that silently switch adjustment
conventions. Python 3.11+, **zero dependencies**, Windows / Linux / macOS.

![adjustment chain](https://img.shields.io/badge/deps-0-brightgreen)
![python](https://img.shields.io/badge/python-3.11%2B-blue)

**Status:** v0.1 —alpha. The adjustment math is battle-tested inside a
production research pipeline, but this standalone package is new: expect the
CLI and schema to shift before v1.0.

## Why this exists

A-share (and most equity) history arrives from vendors in **current-vintage**
adjusted form. Two silent dangers:

1. **The convention itself is not point-in-time.** Prices you see today
   embed every adjustment event that ever happened —including events that
   were announced *after* a historical date. A backtest that uses them reads
   the future.
2. **Vendors switch conventions silently.** One day your data source starts
   serving forward-adjusted prices where it served back-adjusted prices
   yesterday. Nothing in the CSV changes shape; every historical signal
   silently changes value.

`pit-adjuster` rebuilds history from two ingredients —current-vintage
forward-adjusted (qfq) bars plus a **point-in-time corporate-action archive**
—into a fixed-basis back-adjusted (hfq) chain where each day's price depends
only on events whose ex-date is on or before that day. Then it *checks*: did
the rebuild invert the vendor chain correctly, and does the vendor chain
still agree with live raw prices today?

## Philosophy

Price history must be reversible. A research pipeline that cannot prove its
prices were knowable in the past is not doing backtesting —it is doing
wishful thinking. `pit-adjuster` treats **look-ahead freedom as a
verifiable property**, not a style preference:

- **PIT principle** —every price, factor, and calibration depends only on
  information available at that historical point. See
  [Kelly et al., "Scaling Point-in-Time Language Models"](https://www.nber.org/papers/w35247)
  (NBER w35247) and
  [Look-Ahead-Bench](https://ar5iv.labs.arxiv.org/html/2601.13770)
  (arXiv:2601.13770) for why the whole industry is converging on this.
- **Look-ahead bias is measurable** —Daniel, Sornette & Wohrmann (2008),
  ["Look-Ahead Benchmark Bias in Portfolio Performance Evaluation"](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1289222)
  (arXiv:0810.1922) quantify how ex-post benchmark construction inflates
  performance. A vendor that silently swaps adjustment conventions is doing
  exactly this, inside your price column.
- **Formal ground** —Fonseca (2026),
  ["Look-Ahead-Freedom as Temporal Non-Interference"](https://econpapers.repec.org/paper/arxpapers/2607.04958.htm)
  (arXiv:2607.04958) proves look-ahead-freedom is *undecidable* in general
  (Pi-0-1-hard when availability depends on data values), but admits a
  **linear-time decidable type-effect system on the value-independent
  fragment** —windowing, resampling, joins, PIT and vintage reads.

**Honest boundary:** this package implements verifiable checks for the
value-independent fragment of the problem (factor chains, ex-date ordering,
snapshot equivalence, chain inversion). For the general value-dependent case
we fall back to heuristic guards and say so explicitly —verifiability is
claimed only where the theory allows it.

## Quick start

```bash
# install from PyPI (once published)
pip install pit-adjuster

# or run without installing anything:
#   PYTHONPATH=src python -m pit_adjuster --help

# try it on synthetic data (builds a fake qfq history + action archive,
# rebuilds to hfq, runs invert-check and drift-check)
python examples/demo.py
```

Rebuild your own history:

```bash
padj rebuild \
  --bars bars.json --actions actions.json \
  --as-of 2026-08-11 --code 600000 --out hfq.json

padj invert-check --bars hfq.json --actions actions.json --as-of 2026-08-11
padj drift-check --bars hfq.json --actions actions.json \
  --as-of 2026-08-11 --live live_closes.json
```

`padj rebuild` is the workhorse: it inverts the vendor qfq chain back to raw
prices, then re-applies only events whose ex-date is on or before each bar
date (fixed basis at the archive coverage start). Raw open/close are kept
alongside adjusted prices so execution-level work can map back to nominal
prices.

## Commands

| Command | What it does |
| --- | --- |
| `rebuild` | Rebuild bars to fixed-basis hfq: `open/high/low/close` adjusted, `raw_open/raw_close` nominal, `adj_factor` cumulative multiplier, volume normalized to shares |
| `invert-check` | Ex-date continuity sanity check: is `raw_{ex-1} × factor_e ≥ raw_ex`? Informational —real ex-dates carry overnight returns, so violations can be false positives |
| `drift-check` | **Static forward-adjustment detection.** Compares inverted raw closes against live raw closes; divergence above tolerance is authoritative —a vendor chain that no longer matches the archive |
| `snapshot-equivalence` | Compare two rebuilt outputs (e.g. old and new pipeline versions) date-by-date within tolerance —the "did anything change?" gate |
| `version` | Print version |

Global flags: `--help` on every subcommand; JSON outputs via `--out` where
supported; everything else prints a human-readable summary.

## Data model

**Bars** —a JSON list of daily bars, each with at least `date` (ISO) and
`close`; `open/high/low/volume/amount/turnover` are preserved through the
rebuild:

```json
{"date": "2026-06-12", "open": 95.0, "high": 96.0, "low": 94.5, "close": 95.5, "volume": 1234500}
```

**Actions** —a point-in-time corporate-action archive, one record per
event, with `ex_date`, `adjustment_factor` and `available_at`:

```json
{"ex_date": "2026-06-15", "adjustment_factor": 0.95, "available_at": "2026-06-14T18:00:00", "action_type": "cash_dividend_stock_distribution"}
```

Invalid records (missing ex-date, non-positive or non-finite factor) are
dropped; only events with `ex_date <= as_of_date` participate. The schema
lives in [schema/corporate-action.schema.json](https://github.com/foolproof-labs/pit-adjuster/blob/main/schema/corporate-action.schema.json).

## Adjustment math

Standard A-share factor math (as documented by exchange reference-price
rules):

```
factor_e = (prior_close - cash) / (prior_close * (1 + bonus + transfer))
qfq_t    = raw_t * prod_{e: ex_date_e > t} factor_e
hfq_t    = raw_t * prod_{e: ex_date_e <= t} (1 / factor_e)
```

`rebuild` inverts the vendor qfq chain back to raw prices, then applies the
hfq chain with a fixed basis at the archive coverage start. **Key property
(under test):** hfq and qfq yield identical adjusted *returns* for the same
factor chain, while hfq additionally guarantees that a price at time `t` is
untouched by events with ex-date after `t`.

Volume normalization follows the A-share convention: most codes store volume
in lots (×100 to shares); STAR-market codes (688/689 prefixes) store native
shares. Both are parameterizable —see `--volume-to-shares` and the
`native_share_prefixes` argument in `rebuild_bars`.

## Verification model

`pit-adjuster` never trusts its inputs:

- `invert-check` —factor continuity at ex-dates (sanity, false-positive
  tolerant)
- `drift-check` —inverted raws vs live raws (authoritative divergence
  detection; this is the "static forward-adjustment detector" —if a vendor
  swaps conventions, this fires)
- `snapshot-equivalence` —before/after equivalence of two rebuilds, the
  reproducibility gate for pipeline migrations

Every check is read-only. Nothing here trades, prices, or decides.

## Development

```bash
python -m pip install -e . pytest
python -m pytest
```

CI runs the full test suite on Ubuntu, Windows and macOS with Python 3.11 and
3.12. Issues are handled on weekends; pull requests are welcome.

## Related work

- [Daniel, Sornette & Wohrmann (2008)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1289222) —look-ahead benchmark bias, quantified
- [Fonseca (2026)](https://econpapers.repec.org/paper/arxpapers/2607.04958.htm) —look-ahead-freedom as temporal non-interference (the verifiability boundary)
- [Point-in-Time Backtesting: A Formal Bias Taxonomy](https://www.mdpi.com/2227-7390/14/12/2182) (Mathematics 2026, 14(12):2182)
- [Kelly et al., Scaling Point-in-Time Language Models](https://www.nber.org/papers/w35247) (NBER w35247)
- [Look-Ahead-Bench](https://ar5iv.labs.arxiv.org/html/2601.13770) (arXiv:2601.13770) —measuring look-ahead bias in PIT LLMs

## Project family

Part of [Foolproof Labs](https://github.com/foolproof-labs) — a toolchain
against self-deception in quantitative research:

- [pit-adjuster](https://github.com/foolproof-labs/pit-adjuster) — PIT back-adjustment with static forward-adjustment drift detection
- [falsification-ledger](https://github.com/foolproof-labs/falsification-ledger) — pre-registration and falsification ledger
- [factor-qc](https://github.com/foolproof-labs/factor-qc) — fail-closed backtest quality gate
- [lesson-book](https://github.com/foolproof-labs/lesson-book) — tuition memory for traders
- [lookahead-free](https://github.com/foolproof-labs/lookahead-free) — verifiable look-ahead-freedom checks
- [ashare-data-immunity](https://github.com/foolproof-labs/ashare-data-immunity) — data immunity for A-share daily bars

## License

MIT
