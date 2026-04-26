# FOREX.com AU CFD Feasibility (WP-59)

`WP-59` validates whether the broker-neutral CFD core built for IG (Phase 10, `BaseExchange` + `BasePriceFeed` + `CfdInstrumentRegistry`) can be applied to `FOREX.com AU` without structural changes. The short answer: **yes, with one optional capability flag and three adapter-local differences** vs IG. No changes are required to the Phase 10 venue contract, the strategy layer, or the risk layer.

All findings below are from a live session against the demo account (see `Account and API entitlement` below), recorded on 2026-04-18.

---

## Account and API entitlement

- **Host:** `https://ciapi.cityindex.com/TradingApi` (single host serves both live and demo — the `ciapipreprod.cityindextest9.co.uk` host rejects these creds)
- **Env vars (already set in `.env`):** `FOREXDOTCOM_LOGIN`, `FOREXDOTCOM_PASSWORD`, `FOREXDOTCOM_APP_KEY`
- **Account (demo):**
  - `ClientAccountId`: `407561127`
  - `TradingAccountId`: `407617570`, `TradingAccountCode`: `DM912172` (`DM` prefix = demo)
  - `TradingAccountType`: `CFD`, `ClientAccountCurrency`: `AUD`
  - `IsFifo`: `true`, `IsMiFIDRegulator`: `false`, `IsNfaEnabledClient`: `false`
  - Demo expires ~2026-07-07 (80 days from first login)

**Verified endpoints (200 OK):**
- `POST /session` — `{UserName, Password, AppKey}` → `Session` GUID
- `POST /session/validate` — `{UserName, Session}` → `{IsAuthenticated: true}`
- `GET  /useraccount/ClientAndTradingAccount` — returns account metadata above
- `GET  /cfd/markets?MarketName=...` — market search
- `GET  /market/{MarketId}/information` — instrument metadata
- `GET  /market/{MarketId}/barhistory?interval=MINUTE&span=5&PriceBars=N` — historical bars
- `GET  /market/{MarketId}/tickhistory?PriceTicks=N` — last ticks
- `POST /order/simulate/newtradeorder` — order sizing/margin simulation

Docs site (`https://docs.labs.gaincapital.com/`) uses client-side hash routing and is not indexable by `WebFetch` on the landing page; per-endpoint pages resolve at `https://docs.labs.gaincapital.com/Content/<Section>/<Page>.htm`.

---

## Target AU index CFD identifiers

| Canonical id | FOREX.com `MarketId` | `Name` | Currency | Margin | `IncrementSize` | `PriceDecimalPlaces` | `ExpiryUtc` |
|---|---|---|---|---|---|---|---|
| `AU200.cash` | `404709651` | `Australia 200 CFD` | AUD | 5% (step-margined) | `0.1` | `1` | — (perpetual cash) |
| `AU200.fwd`  | `406055157` | `Australia 200 Jun 26 CFD` | AUD | 5% | `0.1` (min web size `1`) | `0` | `2026-06-16` |

Underlying index: `.AXJO` (ASX 200). Exchange: `Sydney Futures Exchange` (`ExchangeId=48`). Both markets are flagged `Market24H: true` with explicit `MarketPricingTimes` / `MarketBreakTimes` carrying `MarketTimeZoneOffsetMinutes: 600` (AEST). Guaranteed orders are enabled on both (`AllowGuaranteedOrders: true`, `GuaranteedOrderMinDistance: 110`, `GuaranteedOrderPremium: 1`).

**Step-margin bands for `AU200.cash` (size in index contracts):**

| Lower bound | Margin factor |
|---|---|
| 0 | 5% |
| 3,600 | 6% |
| 7,200 | 15% |

The registry's flat `margin_rate: 0.05` covers all realistic retail position sizes. The band table becomes relevant only if size > 3,600 — worth surfacing as an adapter-computed margin override when needed, not a registry change.

---

## Order-type and position-model differences vs IG

| Capability | IG | FOREX.com | Impact on Talim |
|---|---|---|---|
| Market order | `POST /positions/otc` (stateless, FOK) | `POST /order/newtradeorder` with current `BidPrice`/`OfferPrice` + `AuditId` from latest quote | **Adapter-local**: fetch tick/quote immediately before order post. No contract change. |
| Limit order | `POST /working-orders/otc` | `POST /order/newstoplimitorder` (TriggerPrice + Direction) | Adapter-local mapping. |
| Stop order | Working-order type `STOP` | Same endpoint as limit, different trigger semantics | Adapter-local. |
| Attached stop/limit | `stopLevel`/`limitLevel` on the same order | `IfDone` child orders on the parent | Adapter-local. |
| Guaranteed stop | `guaranteedStop: true` | `Guaranteed: true` with premium/min-distance from `/market/{id}/information` | Adapter-local. |
| Cancel order | `DELETE /working-orders/otc/{dealId}` | `POST /order/cancel` with `OrderId` | Adapter-local. |
| Position model | `netted` (one position per instrument) | **hedging** — every trade creates a separate `OpenPosition`; closes are **FIFO** (`IsFifo: true` on the account) | **Requires one capability flag** (`position_model: "fifo_stack"`) and a close-order helper in the adapter that collapses Talim's single logical position into one or more FIFO-ordered closes. Strategy/risk code unchanged. |
| Partial fills | Yes | Yes | Same. |
| Streaming prices | Lightstreamer | SignalR via `push.cityindex.com` (client lib or raw SignalR) | Adapter-local; `BasePriceFeed.connect/subscribe` contract already abstracts this. |

---

## Rate-limit, auth, and demo-vs-live differences

| Dimension | IG | FOREX.com |
|---|---|---|
| Auth model | `X-IG-API-KEY` header + session tokens `CST` / `X-SECURITY-TOKEN` from `POST /session` v2 | `AppKey` in body + session GUID returned, sent as `Session` header alongside `UserName` header; no API-key header |
| Session lifetime | Short (30 min idle) — explicit refresh | `POST /session/validate` returns `IsAuthenticated`; re-login on 401 |
| Demo / live split | Separate hosts: `demo-api.ig.com` vs `api.ig.com` | **Same host** for both; the `TradingAccountCode` prefix (`DM…`) and `DaysUntilExpiryForDemo` disambiguate |
| Rate limits | Published per-tier in IG Labs docs | Not published on the pages reachable so far; StoneX historically enforces per-account burst limits — verify empirically during WP-60 soak |
| Idempotency | `dealReference` on order submit | `AuditId` — adapter should generate and record one per order |

---

## Canonical → FOREX.com symbol mapping

Additions to `config/cfd_instruments.json` under `venues.forexcom`:

```json
{
  "venues": {
    "forexcom": {
      "supports_market_orders": true,
      "supports_marketable_limits": true,
      "supports_limit_orders": true,
      "supports_stop_orders": true,
      "supports_attached_stops_limits": true,
      "supports_guaranteed_stops": true,
      "supports_partial_fills": true,
      "supports_working_orders": true,
      "supports_streaming_prices": true,
      "supports_demo": true,
      "supports_live": true,
      "position_model": "fifo_stack",
      "requires_quote_prior_to_order": true
    }
  },
  "instruments": [
    {
      "canonical_id": "AU200.cash",
      "venues": {
        "forexcom": {
          "lookup_hint": "Australia 200",
          "broker_symbol": "404709651",
          "market_id": "404709651",
          "expiry": "-",
          "venue_display_name": "Australia 200 CFD",
          "product_type": "index_cfd",
          "notes": "Verified on demo 2026-04-18. MarginFactor 5%, IncrementSize 0.1, PriceDecimalPlaces 1. Step-margin bands apply above size 3600."
        }
      }
    },
    {
      "canonical_id": "AU200.fwd",
      "venues": {
        "forexcom": {
          "lookup_hint": "Australia 200",
          "broker_symbol": "406055157",
          "market_id": "406055157",
          "expiry": "JUN-26",
          "venue_display_name": "Australia 200 Jun 26 CFD",
          "product_type": "index_cfd",
          "notes": "Verified on demo 2026-04-18. ExpiryUtc ~2026-06-16; roll handling required before expiry."
        }
      }
    }
  ]
}
```

`broker_symbol` is the numeric `MarketId` stringified — consistent with the existing registry's `str` type and does not require a schema change.

---

## Gap analysis against Phase 10 venue contract

### Supported as-is (no change)
- `BaseExchange.place_order(instrument, side, qty, order_type, limit_price, strategy)` — market and limit map to `/order/newtradeorder` and `/order/newstoplimitorder`.
- `BaseExchange.cancel_order(order_id)` — `/order/cancel`.
- `BaseExchange.get_positions()` — `/order/openpositions` returns the raw list; the adapter aggregates FIFO lots into one logical `Position` per `(instrument, side)` to match the Phase 10 `Position` shape.
- `BaseExchange.get_account_balance()` — `/margin/clientaccountmargin` (AUD-denominated; no FX conversion).
- `BaseExchange.get_order(order_id)` — `/order/{OrderId}`.
- `BasePriceFeed.prime_history / poll_once` — `/market/{MarketId}/barhistory` returns 5-min bars compatible with `OHLCVBar`.
- `BasePriceFeed.connect/subscribe` — maps to SignalR subscription per `MarketId` (adapter owns the client library choice).
- Canonical registry schema — no new fields required.
- Risk layer, HITL flow, strategy code — no changes.

### Requires optional capability flags (registry-level only)
- `position_model: "fifo_stack"` — new enum value alongside the existing `netted`. The strategy/risk layer continues to read one logical position per `(instrument, side)`; only the adapter's close path differs.
- `requires_quote_prior_to_order: true` — signals that the adapter must fetch a current `BidPrice`/`OfferPrice` before `/order/newtradeorder`. Today only FOREX.com needs this; IG is unaffected.

### Requires structural changes
- **None.** No change to `BaseExchange`, `BasePriceFeed`, `CfdInstrumentRegistry` dataclasses, `Position`, `Order`, or the risk/strategy layer.

### New code owned by the FOREX.com adapter (WP-60 scope, not WP-59)
- `talim/connectors/exchange/forexcom_exchange.py` — session mgmt, order translation, FIFO close helper, AuditId generation.
- `talim/connectors/pricefeed/forexcom.py` — SignalR subscriber + barhistory backfill.
- `talim/connectors/exchange/forexcom_discovery.py` — market search + registry patch builder (mirrors `ig_discovery.py`).
- Env-driven credentials dataclass (`FxComCredentials` with `login/password/app_key`, reused for both sub-adapters).

---

## Go / No-Go

**Go.** All four go-criteria from the IG feasibility doc hold on FOREX.com:

- Demo API auth succeeds consistently (`POST /session` 200, `StatusCode: 1`, session validates).
- A specific `Australia 200` tradable market is discoverable (`MarketId: 404709651`) and `/market/{id}/information` returns sufficient metadata.
- Instrument metadata populates every previously-unresolved registry field (tick via `IncrementSize`, decimals via `PriceDecimalPlaces`, margin via `MarginFactor`, session via `MarketPricingTimes`/`MarketBreakTimes`).
- Price feed path (REST bar history + SignalR streaming) is available under normal trading entitlement without paid add-ons.

**Caveats to carry into WP-60:**

- Demo account expires ~2026-07-07; soak work after ~2026-07-01 needs a refreshed account.
- Rate limits are not publicly documented on the pages reachable so far — measure empirically during soak.
- SignalR streaming has not yet been exercised end-to-end; if the chosen client library is heavy, fall back to REST `/market/{id}/tickhistory` polling for the PoC.
- FIFO close behaviour needs at least one manual demo trade confirming that closing via `/order/close` resolves lots in the expected order.
