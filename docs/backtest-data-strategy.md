# Backtest Data Strategy (WP-67)

**Status:** Decided 2026-04-19.
**Decision:** Use IG and FOREX.com historical REST as the primary backtest
data sources. **No QuantConnect.** Keep one strategy implementation shared
between live and backtest via `BaseStrategy.on_bar`.

---

## Invariants we are preserving

1. A strategy's code runs **unchanged** in live and backtest. One
   `BaseStrategy.on_bar` implementation is the contract. No parallel SDK
   rewrites.
2. Backtest data comes from the **same venue** Talim trades on, so backtest
   microstructure (spread, session, holiday calendar, contract specs)
   matches live as closely as possible.
3. Data ingestion is **free** and runs against existing demo credentials.

---

## Strategy-vs-data coverage matrix

| Strategy | Intended market | Live-reachable via | Data status |
|---|---|---|---|
| `momentum-AU200` | Australia 200 cash CFD | IG, FOREX.com | `data/ig/AU200.cash/{1h,1d}.parquet` (baseline run on IG demo) |
| `momentum-US500` (renamed from `momentum-ES` in WP-73) | S&P 500 (via US500 CFD, not ES futures — we don't trade CME) | IG, FOREX.com | `data/ig/US500.cash/{5m,1h}.parquet` (ingest in WP-73). |
| `mean-reversion-US500` (renamed from `mean-reversion-ES` in WP-73) | S&P 500 (via US500 CFD) | IG, FOREX.com | `data/ig/US500.cash/{5m,1h}.parquet` (ingest in WP-73). |
| Planned RSI/MACD strategies | TBD (likely US500 + FX majors) | IG, FOREX.com | Extend registry + ingest per instrument. |

The "ES" naming was a leftover from an earlier US futures framing. The
current live rails are CFDs, not CME. US500 on IG/FOREX.com is the right
wrapper for the same underlying index. WP-73 renames and repurposes.

---

## Candidate data sources considered

| Source | Coverage relevant to us | Cost | Verdict |
|---|---|---|---|
| **IG historical REST** | All CFDs we can trade on IG (indices, FX, commodities, equities), 1m/5m/1h/1d | Free with existing demo account | **Chosen (primary).** Matches live venue; ingest already wired (WP-51, `scripts/ingest_ig_prices.py`). |
| **FOREX.com historical REST** | All CFDs we can trade on FOREX.com | Free with existing demo account | **Chosen (secondary).** Matches second live venue; ingest wired (WP-60). |
| Yahoo Finance / `yfinance` | Equities, ETFs, indices, FX, crypto | Free | Rejected. 5m bars are only ~60-day rolling — too short for Sharpe/max-DD to be meaningful. |
| Dukascopy | FX tick/1m, long history | Free | Deferred. FX-only, and IG already covers the FX majors we care about for now. |
| Binance public | Crypto | Free | Deferred. We don't trade crypto. |
| Polygon | US equities + options | Free tier is delayed + limited | Rejected. Equities-only and live rails don't go there. |
| Databento | Institutional tick data | Paid | Rejected. Not free. |
| **QuantConnect (LEAN + data library)** | Huge — CME futures, equities, FX, options, crypto | Free inside their cloud | **Rejected, see below.** |

### Why not QuantConnect

QuantConnect's hosted data library is genuinely excellent and would
trivially provide ES, US500, and more at any granularity. We are not using
it because adopting it would require one of the following, and each breaks
an invariant:

- **Port strategies to LEAN's event API** — breaks invariant 1 (single
  strategy code for live + backtest). We'd own two implementations and
  they'd drift. Exactly the class of bug live-vs-backtest divergence
  produces.
- **Build a `BaseStrategy` → LEAN adapter** — possible but non-trivial,
  and still only solves backtest while live runs via our own broker
  adapters. We'd also inherit LEAN's data-handle semantics (warmup,
  consolidators) in our strategy classes.
- **Download QC data and use our engine** — QC's licensing for bulk
  download outside the cloud is restrictive; not a free path.

We will **revisit** QuantConnect only if: (a) we need instruments IG and
FOREX.com don't offer (e.g. specific CME options chains), or (b) we decide
to run a dedicated research environment separate from the production path.

---

## Constraints for WP-73 (execution)

WP-73 is the execution half. Given this decision, WP-73 must:

1. Use `scripts/ingest_ig_prices.py --timeframe 5m` as the primary ingest
   path. It already supports 5m, append/dedup, and writes
   `data/ig/{instrument}/{tf}.parquet` + `dataset-manifest.json`.
2. **Rename** `strategies/momentum-ES` → `strategies/momentum-US500` and
   `strategies/mean-reversion-ES` → `strategies/mean-reversion-US500`.
   Update class names, `name` properties, vectorbt translator keys,
   test fixtures, and any references in docs.
3. **Add** `US500.cash` to `config/cfd_instruments.json` after resolving
   the IG epic with `scripts/ig_market_discovery.py`. FOREX.com mapping
   can wait (IG is enough to unblock backtesting).
4. Ingest **5m and 1h** history for US500.cash. Target: enough history to
   cover several regime changes (3+ years if IG permits; IG's REST caps
   are ~30,000 bars per request, so append in chunks).
5. Produce a **baseline backtest** for both `momentum-US500` and
   `mean-reversion-US500` at default parameters, persisted through WP-68's
   history table when that lands (until then, commit the metrics under
   `docs/backtest-baselines/`).
6. Update `scripts/run_backtest.py` to **fail loudly** on missing
   instrument/timeframe — no silent empty backtests. This applies whether
   or not US500 ends up being the first user.

---

## Out of scope (explicit deferrals)

- **FOREX.com US500 mapping.** Nice to have for cross-venue parity
  (WP-61 style) but not blocking WP-73. Follow-up WP.
- **Tick data.** Not free at meaningful scale; defer until a strategy
  actually needs sub-minute microstructure.
- **More instruments** (US100, GBPUSD, EURUSD, Gold, etc.). Add one at a
  time as strategies need them; the ingest tooling is now shaped like a
  per-instrument loop, so adding each is a ~10-line config + an ingest
  run, not a new WP.
- **Options / futures chains.** Out of scope for the CFD product; would
  reopen the QuantConnect question.

---

## Summary

- **Primary backtest data source:** IG historical REST (demo credentials).
- **Secondary:** FOREX.com historical REST.
- **No QuantConnect.** Single strategy contract for live + backtest
  remains load-bearing.
- **First target for WP-73:** US500.cash (rename from the existing `-ES`
  strategies).
- **Granularity:** 5m primary, 1h secondary.
