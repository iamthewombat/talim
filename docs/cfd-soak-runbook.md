# Multi-Broker CFD Soak Runbook (WP-61)

This is the shared regression + demo-soak procedure for any broker adapter that implements the Phase 10 CFD venue contract (`BaseExchange` + `BasePriceFeed` + `CfdInstrumentRegistry`). It is written to work identically against `IG AU` and `FOREX.com AU` demo accounts. New venues should pass this same checklist before being promoted to live.

The point of this doc is to prove that the **strategy and risk layers cannot tell one venue from another** — any observable difference between brokers after this runbook is a bug in the adapter, not in Talim.

---

## Scope

- Canonical instrument: `AU200.cash` (extend to `AU200.fwd` once the expiry-roll test lands)
- Strategy: `momentum-AU200`
- Venues under test: `ig`, `forexcom`
- Mode: demo only — this runbook never places real capital

Anything broker-specific (endpoint paths, credential envs, session lifetime) lives in the adapter and its feasibility doc:

- [docs/ig-cfd-feasibility.md](../docs/ig-cfd-feasibility.md:1)
- [docs/forexcom-cfd-feasibility.md](../docs/forexcom-cfd-feasibility.md:1)

---

## Regression Checklist

Run this before starting any soak session, and re-run it after any change that touches `talim/connectors/exchange/`, `talim/connectors/pricefeed/`, `talim/cfd/`, or adapter factories. The conformance suite at [tests/test_cfd_conformance.py](../tests/test_cfd_conformance.py:1) automates items 1-5 across both venues.

### 1. Canonical instrument resolution

- `registry.get("AU200.cash")` returns the same `CfdInstrumentSpec` (currency, asset class, tick size, margin rate) regardless of venue.
- `registry.resolve_mapping("AU200.cash", "<venue>").is_resolved` is `True` for every adapter under test.
- Instruments surfaced by `BaseExchange.get_positions()` come back as the canonical id, not the broker-native symbol (`IX.D.ASX.IFT.IP` for IG, `404709651` for FOREX.com).

### 2. Order placement semantics (market + limit)

- Market `place_order(..., "buy", qty)` returns `OrderStatus.FILLED` with a non-null `fill_price`.
- Market entries created from strategy signals include attached stop/target
  protection when the venue capability says attached stops/limits are
  supported.
- Limit `place_order(..., order_type="limit", limit_price=...)` returns `OrderStatus.OPEN` and the `limit_price` echoes the caller's value.
- The returned `Order.instrument` is canonical (`AU200.cash`), never the broker-native symbol.
- FOREX.com only: the adapter fetches a tick (`/market/{id}/tickhistory`) and forwards `BidPrice` / `OfferPrice` / `AuditId` in the same request cycle. Absence of any of those fields means the quote step was skipped.

### 3. Stop / limit working-order lifecycle

- Stop and target levels from the approved `Signal` are visible on the
  submitted broker payload and on the returned `Order.stop_price` /
  `Order.target_price`.
- Exit signals call `BaseExchange.close_position(...)`; a long exit sells the
  open position and a short exit buys it back. If no matching position exists,
  execution must skip rather than open a new opposite position.
- After a successful `cancel_order(order_id)`, `get_order(order_id)` returns `status == OrderStatus.CANCELLED` from the local cache.
- Cancellation is idempotent from the strategy layer's perspective — a second cancel on the same id does not raise.
- Working-order listing (where the venue supports it) returns canonical instruments.

### 4. Position canonicalisation

- `get_positions()` returns a single logical `Position` per (canonical instrument, side).
- For FOREX.com (`fifo_stack`), multiple broker-side lots on the same side collapse into one `Position` with VWAP entry price and summed `qty`.
- For IG (`netted`), a single broker position maps 1:1.
- `position_id` is stable within a session (for FIFO adapters, the oldest lot's id surfaces as the logical id).

### 5. Balance / margin shape

- `get_account_balance()` returns a `dict[str, float]` keyed by ISO currency code (e.g. `{"AUD": 48000.0}`).
- The value represents withdrawable / tradable funds, not gross equity — margin already deducted.
- The currency matches the broker's account currency and the canonical instrument's `quote_currency`.

### 6. Bar continuity (price feed)

- `prime_history("AU200.cash", min_bars=N)` returns at least `N` fully closed bars in ascending timestamp order.
- `poll_once("AU200.cash")` emits a bar only when the latest closed bar is strictly newer than the previous emission — no duplicates across polls.
- Partial / in-progress bars are never surfaced to `on_bar` subscribers.
- Timeframes map correctly (`5m`, `1h`, `1d`).

### 7. Session handling

- Session tokens are created once per adapter instance and reused across requests.
- A 401 / session-expired response triggers a single transparent re-auth, then retries the original call.
- `.env` credential envs are loaded via `<VENUE>Credentials.from_env()` and no bare strings are logged.

### 8. Commands

```bash
./.venv/bin/pytest tests/test_cfd_conformance.py -q
./.venv/bin/pytest tests/test_ig_exchange.py tests/test_ig_pricefeed.py \
    tests/test_forexcom_exchange.py tests/test_forexcom_pricefeed.py \
    tests/test_forexcom_discovery.py -q
./.venv/bin/pytest -q --ignore=tests/e2e
```

All three must be green before starting a soak window.

---

## Demo Soak Procedure

A soak is a multi-session run of `momentum-AU200` on demo credentials. The goal is to observe identical strategy behaviour across both venues under real market data.

### Prep (once per venue)

1. Confirm the adapter's demo credentials are live:
   - IG: `IG_API_KEY`, `IG_IDENTIFIER`, `IG_PASSWORD` → `scripts/verify_ig_session.py`
   - FOREX.com: `FOREXDOTCOM_LOGIN`, `FOREXDOTCOM_PASSWORD`, `FOREXDOTCOM_APP_KEY` → session validate returns `IsAuthenticated: true`
2. Confirm canonical mapping resolves for both venues in `config/cfd_instruments.json`.
3. Build the baseline dataset (IG historical) and accept FOREX.com's rolling bar window — see [docs/au200-demo-soak.md](../docs/au200-demo-soak.md:1) for the IG dataset profiles.

### Config (per soak window)

Set one venue at a time — do not run both adapters against the same Talim instance during a soak, since divergent fills would make reconciliation ambiguous.

```env
TALIM_EXCHANGE_MODE=testnet
TALIM_EXCHANGE_NAME=ig           # or forexcom
TALIM_PRICEFEED=ig               # or forexcom
TALIM_PRICEFEED_TIMEFRAME=1h
```

State:

- `active_strategies=["momentum-AU200"]`
- `instrument="AU200.cash"`
- `default_qty=1`
- `max_margin_utilization_pct <= 0.5`

### Per-Session Checks

Run through these every trading session while the soak is active:

- [ ] Auth succeeds before market open for the selected venue.
- [ ] Scanner `current_bar` advances on schedule at the configured timeframe.
- [ ] No session-window rejections occur during valid AU market hours.
- [ ] Every approval/rejection round-trips cleanly via the assistant bridge.
- [ ] `get_positions()` returns canonical `AU200.cash` (never the native symbol).
- [ ] `get_account_balance()` reports the expected currency (`AUD`).
- [ ] Metrics show no spike in `adapter_reauth_total` or 401 responses.

### Daily Review

- Run `POST /talim/sync?thread_id=cron-main` and compare Talim's checkpointed
  position state against the broker's open positions.
- Check `episodic_memory` for every `momentum-AU200` decision — reason, regime, and whether risk blocked it.
- For FOREX.com specifically: verify FIFO aggregation still collapses multiple lots into a single logical `Position` after partial closes.
- For IG specifically: verify netted reconciliation has not drifted after overnight financing adjustments.

### Cross-Venue Parity (weekly, once per soak)

Run the same strategy against the same calendar week on both venues, then diff:

- signal count per session (should match within `±1` for a strategy that does not depend on broker-specific price micro-structure)
- fill side and quantity (must match exactly)
- per-day `daily_pnl` sign (must match; magnitudes differ by spread + financing)
- reconciliation-drift events (must be zero on both)

Any parity break is a bug report against the adapter that deviates — write it up with the canonical id, session timestamp, both venues' raw responses, and the expected canonical output.

### Go / No-Go Exit Criteria

Go (per venue):

- Zero unexplained reconciliation drift across the full soak window.
- Zero duplicate or stale pending signals.
- Zero auth/feed outages that required manual restart.
- Strategy behaviour matches the IG baseline backtest ([docs/au200-backtest-baseline.md](../docs/au200-backtest-baseline.md:1)) within expected broker-spread bounds.
- Cross-venue parity holds for at least one full weekly window.

No-Go (per venue):

- Repeated drift between Talim state and broker state.
- Session-gate mismatches around AU200 market hours.
- Instability in order placement, cancellation, or position readback.
- Strategy decisions materially diverge from the backtest baseline in ways that cannot be attributed to spread or financing.

### After the Soak

Record the outcome per venue in [docs/au200-soak-review-template.md](../docs/au200-soak-review-template.md:1). A venue only graduates to live after a clean demo soak and a separate live-credentials sign-off.

---

## Adding a new CFD venue

When onboarding a third broker, the acceptance gate is:

1. Feasibility doc lands at `docs/<venue>-cfd-feasibility.md` with endpoint verification, identifier resolution, and gap analysis vs the Phase 10 contract.
2. Adapter implements `BaseExchange` + `BasePriceFeed` with no changes to the contracts or the strategy/risk layers. If a contract change is unavoidable, it must be backwards compatible for existing venues.
3. `tests/test_cfd_conformance.py` gains a `VenueFixture` entry for the new venue and every parametrised test passes.
4. A demo soak window completes against the new venue with this runbook, and cross-venue parity holds against at least one existing venue.
