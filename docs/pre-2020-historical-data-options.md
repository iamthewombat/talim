# Pre-2020 Historical Data Options

**Status:** source shortlist updated 2026-05-05.

## Current Talim dataset shape

Existing FOREX.com files already use the schema Talim wants for backtests:

```text
instrument, timestamp, open, high, low, close, volume, timeframe, price_type, source, fetched_at_utc
```

Current local FOREX.com coverage:

| Instrument | Timeframe | Range | Rows | Notes |
|---|---:|---|---:|---|
| `US500.cash` | `1h` | 2020-01-01 23:00 UTC -> 2026-05-01 11:00 UTC | 113,961 raw / 37,987 backtest copy | Good from 2020 onward |
| `US500.cash` | `5m` | 2021-05-02 22:00 UTC -> 2026-05-01 11:55 UTC | 1,063,454 | No pre-2021 5m from current FOREX.com ingest |
| `AU200.cash` | `1h` | 2020-01-01 22:00 UTC -> 2026-04-29 15:00 UTC | 108,087 raw / 36,029 backtest copy | Good from 2020 onward |
| `AU200.cash` | `5m` | 2021-04-30 00:00 UTC -> 2026-04-29 15:25 UTC | 945,018 | No pre-2021 5m from current FOREX.com ingest |

The highest-compatibility outcome is another source that can be normalised to exactly this schema and stored under a separate source directory, e.g. `data/<source>/<instrument>/<timeframe>.parquet` or `data/backtest/<dataset-name>/<instrument>/<timeframe>.parquet`.

## Ranked shortlist

### 1. IG historical REST — free, most compatible if coverage is deep enough

- **Type:** broker CFD bars.
- **Why it matters:** Same style of product as live CFD execution. Best chance of matching CFD sessions/holidays/spread behaviour.
- **Known issue:** Earlier ingest was blocked by IG weekly allowance, not necessarily by historical depth.
- **Next action:** Re-probe `US500.cash` and `AU200.cash` for `5m`, `1h`, `1d` with explicit old starts. Record per-timeframe floor.
- **Storage:** `data/ig/<instrument>/<timeframe>.parquet`, source `ig`.

### 2. Dukascopy Historical Data Export — free, promising broker-style proxy

- **Type:** free historical export; forex, commodities, and indices; CSV/JForex export; tick through monthly timeframes.
- **Why it matters:** Most promising free non-IG/FOREX.com source for long intraday history that may include index CFD-like instruments.
- **Observed floor checks:** raw datafeed probes found `USA500IDXUSD` available by 2012/2015 and `AUSIDXAUD` available by 2015/2020; `EURUSD` exists at least by 2007 in the same feed. Treat these as approximate symbol/date floors until a proper downloader confirms earliest non-empty trading days.
- **Risk:** Need symbol-level proof, timestamp/session validation, and a terms/licence check before depending on it.
- **Prototype status:** `scripts/ingest_dukascopy_ticks.py` now downloads BI5 ticks, decodes, aggregates, and writes Talim Parquet. One-hour 2015 samples succeeded for `USA500IDXUSD` and `AUSIDXAUD` under `data/backtest/dukascopy-sample/`.
- **Next action:** Extend the importer with a coverage scanner/resume manifest, then download full years in controlled batches.
- **Storage:** keep separate as `source=dukascopy`; do not merge into `forexcom`.

### 3. Stooq historical archives — free, good proxy data

- **Type:** free daily/hourly/5-minute archives.
- **Evidence:** Stooq publishes bulk ASCII archives for World, US, UK, Hong Kong, etc. 5-minute US and world archives are available as downloadable zip bundles. Stooq `^SPX` daily page runs back to 1789 in the web table; `SPY.US` daily runs back to 2005-02-25. Direct symbol CSV downloads now require an API-key/captcha flow. Web historical pages did not expose hourly/5m rows for `^SPX`/`SPY.US`; those need bulk archive inspection.
- **Why it matters:** Best quick free source for broad proxy research, especially S&P 500 / SPY-style data.
- **Risk:** Proxy only — not CFD venue-compatible. Australia 200 symbols were not obvious from quick checks.
- **Next action:** Pull relevant bulk archives, locate `^SPX`/`SPY` and possible Australia 200 symbols, import to `source=stooq`.

### 4. FirstRate Data — paid, best practical paid starting point

- **Type:** paid downloadable CSV datasets.
- **Evidence:** SPX index intraday from 2008-01-02 to current; 1m, 5m, 30m, 1h, 1d OHLC. ES futures also from 2008-01-02 with continuous and individual contracts; includes unadjusted, absolute-adjusted, and ratio-adjusted continuous series. Samples download cleanly and match an easy CSV shape.
- **Pricing notes:** static pages expose free samples and 1 month of updates; ongoing daily updates are advertised at $99.95/year. The one-off dataset price is loaded through checkout and was not visible in static fetch; confirm in browser before purchase.
- **Why it matters:** Likely the fastest paid way to get reliable pre-2020 S&P backtest data into Talim.
- **Risk:** SPX/ES are proxies for `US500.cash`, not FOREX.com CFDs. Need choose whether SPX cash index or ES continuous futures is the better research proxy.
- **Next action:** Import free samples first; if shape is acceptable, buy SPX or ES before considering bigger bundles.

### 5. Kibot — paid, long intraday/tick history

- **Type:** paid stocks, ETFs, futures, forex; minute and tick data.
- **Evidence:** Vendor claims 28+ years of 1-minute intraday and 17+ years of tick bid/ask for stocks, ETFs, futures, and forex.
- **Pricing notes:** public buy page shows many package prices ranging roughly $50 to $3,750 depending asset universe and granularity; exact relevant ES/SPY package needs selection.
- **Why it matters:** Good if we want long SPY/ES-style data with 1-minute granularity and possibly bid/ask.
- **Risk:** Less directly CFD-compatible; package selection/pricing needs review.

### 6. Portara / CQG Data Factory — paid professional futures

- **Type:** paid futures, forex, cash commodities, fixed income, stock indices; daily/intraday/tick; continuous and individual contracts.
- **Evidence:** Covers e-mini S&P and many stock index futures; advertises 1-minute/tick packages and continuous futures expertise.
- **Pricing notes:** one-off data purchases advertised at about $220-$330 per commodity for full history; subscriptions are custom quoted.
- **Why it matters:** Strong option if Talim moves from CFD proxy research into futures-grade research.
- **Risk:** More expensive/heavier than needed for first pass. Sales-led rather than simple API/download.

### 7. TickData — paid institutional/research grade

- **Type:** paid global intraday data for equities, futures, options, forex, and cash indices.
- **Why it matters:** Highest-quality option if we need institutional-grade cash index/futures history and can justify cost.
- **Risk:** Likely overkill until cheaper/free sources prove insufficient.

## Lower-priority / probably not enough

- **EODHD:** Intraday API is convenient, but documented 5m/1h availability starts around October 2020 for many instruments/exchanges; not enough for the pre-2020 gap.
- **Twelve Data:** Broad API coverage, but needs specific symbol/history verification and is less obviously deep enough for our 5m pre-2020 need.
- **Yahoo/yfinance:** Intraday retention is too short for this job.
- **Alpha Vantage:** Useful API, but index/intraday depth and premium constraints make it less attractive than Stooq/FirstRate for this specific need.

## Recommended implementation path

1. **Probe broker-compatible sources first**
   - Re-run IG historical ingest now that allowance may have reset.
   - Re-run FOREX.com with explicit pre-2020 starts to confirm true floor.
   - Dukascopy sample importer is working for `USA500IDXUSD` and `AUSIDXAUD`; next step is full coverage scanning/downloading.

2. **Build a generic external-data importer**
   - Input: vendor CSV/API.
   - Output: Talim OHLCV Parquet schema.
   - Required manifest: vendor, symbol, mapped Talim instrument/proxy, timezone, session assumptions, price type, licence notes, import command.

3. **Use separate datasets for proxies**
   - Do not contaminate `data/forexcom` with SPX/ES/Stooq proxy data.
   - Use dataset names like `data/backtest/stooq-spx-proxy/US500.proxy/5m.parquet` or `data/backtest/firstrate-es-continuous/US500.proxy/5m.parquet`.

4. **Buy only after sample import passes**
   - First paid purchase should be FirstRate SPX or ES, because samples are easy and coverage starts in 2008.
   - Validate timezone/session/gaps and run a smoke backtest before broader spend.
