# AU200 IG Demo Soak

This is the first operational runbook for `momentum-AU200` on `IG AU`.

## Scope

- Broker: `IG AU` demo
- Canonical instrument: `AU200.cash`
- Baseline backtest timeframe: `1h`
- Live/demo scanner timeframe: start at `1h`; only move to `5m` after a separate warmup pull

## Why This Split Exists

IG's default historical-data allowance is `10,000` points per week. That is enough for:

- a rolling `360`-day `1h` baseline dataset
- a `2`-year `1d` context dataset

It is not enough to pull a multi-year `5m` dataset in one shot. Treat `5m` as a rolling execution dataset that accumulates over time.

## Dataset Profiles

### Baseline Backtest Profile

Build the baseline validation set:

```bash
./.venv/bin/python scripts/build_au200_dataset.py --profile backtest-baseline
```

This writes:

- `data/ig/AU200.cash/1h.parquet`
- `data/ig/AU200.cash/1d.parquet`
- `data/ig/AU200.cash/dataset-manifest.json`

### Optional Execution Warmup Profile

After the IG historical allowance resets, build a `5m` warmup set:

```bash
./.venv/bin/python scripts/build_au200_dataset.py --profile execution-warmup
```

This writes:

- `data/ig/AU200.cash/5m.parquet`

## Backtest Command

Run the baseline AU200 backtest:

```bash
./.venv/bin/python scripts/run_backtest.py \
  --strategy momentum-AU200 \
  --instrument AU200.cash \
  --timeframe 1h \
  --data-dir data/ig \
  --params '{"ema_fast_period": 13, "ema_slow_period": 34}' \
  --params '{"ema_fast_period": 10, "ema_slow_period": 30, "min_ema_gap_atr": 0.10}'
```

The first recorded baseline run is in [docs/au200-backtest-baseline.md](/Users/justinluu/code/paige/talim/docs/au200-backtest-baseline.md:1).

## Demo Configuration

Recommended initial config:

```env
TALIM_EXCHANGE_MODE=testnet
TALIM_EXCHANGE_NAME=ig
TALIM_PRICEFEED=ig
TALIM_PRICEFEED_TIMEFRAME=1h
```

Recommended state:

- `active_strategies=["momentum-AU200"]`
- `instrument="AU200.cash"`
- `default_qty=1`
- keep `max_margin_utilization_pct` at `<= 0.5` during demo

## Two-Week Soak Checklist

### Every Session

- Verify IG auth succeeds before market open.
- Verify the scanner updates `current_bar` on schedule.
- Confirm no session-window rejections occur during valid market hours.
- Confirm all approvals/rejections propagate cleanly through the assistant path.
- Review `open_pnl`, `daily_pnl`, and `margin_in_use`.

### Daily Review

- Compare Talim state to IG positions.
- Check for reconciliation alerts.
- Review every `momentum-AU200` decision in episodic memory.
- Record whether a signal was blocked by margin, session, or correlation logic.

### Go / No-Go Exit Criteria

Go:

- no unexplained reconciliation drift
- no duplicate or stale pending signals
- no auth/feed outages that require manual restart during the soak
- backtest assumptions still broadly match live bar behaviour

No-Go:

- repeated drift between Talim and IG
- session-gate mismatches around AU200 market hours
- order placement or confirm lookup instability
- strategy behaviour that materially diverges from the backtest baseline

After the soak, write the decision into [docs/au200-soak-review-template.md](/Users/justinluu/code/paige/talim/docs/au200-soak-review-template.md:1).
