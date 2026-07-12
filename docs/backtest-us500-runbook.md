# US500 Backtest Runbook (WP-73)

This runbook is the step-by-step procedure for ingesting US500.cash
history and producing baseline backtests for the two PoC strategies
(`momentum-US500`, `mean-reversion-US500`).

WP-73 renames what used to be `momentum-ES` and `mean-reversion-ES` to
target the US500 index CFD — the same underlying index that maps onto
IG's `IX.D.SPTRD.IFA.IP` and FOREX.com's `US SP 500 CFD` (market id
`404706660`). We do not trade CME ES futures.

## Prerequisites

1. IG demo credentials in `.env` (`IG_DEMO_API_KEY`, `IG_DEMO_LOGIN`,
   `IG_DEMO_PASSWORD`) and/or FOREX.com demo credentials
   (`FOREXCOM_APP_KEY`, `FOREXCOM_USERNAME`, `FOREXCOM_PASSWORD`).
2. Registry entry for `US500.cash` in
   `config/cfd_instruments.json` — added in WP-73 with both IG and
   FOREX.com mappings.
3. Python environment with the project installed (`pip install -e .`).

## 1. Verify the registry entry

```bash
.venv/bin/python -c "
from talim.cfd import load_default_registry
r = load_default_registry()
m = r.resolve_mapping('US500.cash', 'ig')
print('IG epic:', m.broker_symbol, '—', m.venue_display_name)
m = r.resolve_mapping('US500.cash', 'forexcom')
print('FC id :', m.broker_symbol, '—', m.venue_display_name)
"
```

Expected output:

```
IG epic: IX.D.SPTRD.IFA.IP — US 500 Cash (A$1)
FC id : 404706660 — US SP 500 CFD
```

## 2. Ingest historical bars

### IG (primary; subject to weekly allowance)

```bash
.venv/bin/python scripts/build_au200_dataset.py \
    --instrument US500.cash \
    --profile backtest-baseline \
    --manifest data/ig/US500.cash/manifest-baseline.json

.venv/bin/python scripts/build_au200_dataset.py \
    --instrument US500.cash \
    --profile execution-warmup \
    --manifest data/ig/US500.cash/manifest-warmup.json
```

IG caps demo accounts at a weekly bar allowance (typically ~10k bars).
If you see
`error.public-api.exceeded-account-historical-data-allowance`,
stop and wait for the Monday (UTC) reset — there is no way to
bypass it short of using a different account.

### FOREX.com (secondary; ~4000-bar cap per request)

```bash
.venv/bin/python scripts/ingest_forexcom_prices.py \
    --instrument US500.cash --timeframe 1h --bars 4000

.venv/bin/python scripts/ingest_forexcom_prices.py \
    --instrument US500.cash --timeframe 5m --bars 4000
```

FOREX.com's `barhistory` endpoint caps at ~4000 bars per call and
does not currently accept a `from` parameter in our client. Deeper
history requires extending `ingest_forexcom_prices.py` with
time-windowed pagination.

## 3. Run the baseline backtests

The CLI now requires `--instrument` and fails loudly if the requested
timeframe's parquet is missing (WP-73 hardening of `data_loader`).

```bash
# Against FOREX.com data
.venv/bin/python scripts/run_backtest.py \
    --strategy momentum-US500 --instrument US500.cash \
    --timeframe 1h --data-dir data/forexcom --no-history

.venv/bin/python scripts/run_backtest.py \
    --strategy momentum-US500 --instrument US500.cash \
    --timeframe 5m --data-dir data/forexcom --no-history

.venv/bin/python scripts/run_backtest.py \
    --strategy mean-reversion-US500 --instrument US500.cash \
    --timeframe 1h --data-dir data/forexcom --no-history

.venv/bin/python scripts/run_backtest.py \
    --strategy mean-reversion-US500 --instrument US500.cash \
    --timeframe 5m --data-dir data/forexcom --no-history
```

When ingesting from IG instead, pass `--data-dir data/ig`.

Drop `--no-history` to persist runs into the WP-68 history store
(`state/backtest_history.db` by default, or
`$TALIM_BACKTEST_HISTORY_DB`). Recorded runs are queryable via
`GET /talim/operator/backtests`.

## 4. Baseline snapshots

The original frictionless default-parameter numbers are committed under
`docs/backtest-baselines/us500-2026-04-19.json` (superseded once a costed
snapshot lands). Since WP-86, baselines are re-recorded in one step with
standard venue costs applied:

```bash
.venv/bin/python scripts/rerecord_baselines.py
```

This runs every entry in `config/backtest_baselines.json` (US500 momentum +
mean-reversion on 5m/1h, AU200 momentum on 1h), records each variant to the
history DB with `triggered_by="baseline"`, and writes
`docs/backtest-baselines/baselines-<date>.json` — commit that file. Use
`--allow-partial` if one venue's dataset is not ingested yet.

Re-run after any change to strategy defaults, ingest pipeline, cost
assumptions, or the fill-model in `talim/backtest/engine.py`.

Default-parameter Sharpe is negative on both strategies and both
timeframes; this is the starting point for parameter sweeps, not a
finished system. Tuning lives in a separate WP.

## Known limitations

- **IG weekly allowance.** If the allowance is exhausted, FOREX.com is
  the usable fallback. Re-run against IG when the quota resets to
  cross-verify.
- **FOREX.com 4000-bar cap.** The 5m slice only covers ~2.5 weeks;
  Sharpe and max-DD numbers on 5m are under-powered until pagination
  lands.
- **No 1d slice from FOREX.com yet.** `build_au200_dataset.py` fills
  1d from IG; FOREX.com ingest is 5m/1h only because daily data from
  FOREX.com has not been wired through the price feed's timeframe
  map as a priority.
