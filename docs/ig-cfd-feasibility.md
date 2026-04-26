# IG AU CFD Feasibility

`WP-49` makes `IG AU` the first concrete CFD venue for Talim because IG exposes:

- public REST and streaming API docs via [IG Labs](https://labs.ig.com/)
- demo and live API environments via the [IG AU API page](https://www.ig.com/au/trading-platforms/trading-apis)
- explicit AU index CFD support, including `Australia 200`, on the same API page and on the [ASX 200 product page](https://www.ig.com/au/indices/how-to-trade-invest-asx-200)

## Why IG First

Compared with less-documented CFD venues, IG gives Talim a clean first implementation target:

- documented session bootstrap and rate limits: [IG Labs FAQ](https://labs.ig.com/faq.html)
- market discovery and dealing rules via REST: [REST trading guide](https://labs.ig.com/rest-trading-api-guide.html)
- real-time prices via Lightstreamer: [streaming guide](https://labs.ig.com/streaming-api-guide.html)
- AU retail margin reference for `Australia 200`: [IG AU margin](https://www.ig.com/au/charges/margin)

## Initial Scope

The canonical CFD registry in [config/cfd_instruments.json](../config/cfd_instruments.json:1) starts with:

- `AU200.cash`
- `AU200.fwd`

These are intentionally provisional. The registry tracks:

- canonical ids
- financing model
- AU session window
- IG lookup hints

The IG epic, minimum deal size, and other trade-critical fields remain unresolved until discovery is run against a real demo/live account.

## Demo Discovery Results

On April 12, 2026, the demo discovery script resolved these initial IG mappings:

- `AU200.cash` -> `IX.D.ASX.IFT.IP` (`Australia 200 Cash (A$1)`)
- `AU200.fwd` -> `IX.D.ASX.FWM2.IP` (`Australia 200 (A$5)`, expiry `JUN-26`)

What the demo account returned:

- both instruments were discoverable through the documented REST market search
- both returned `min_deal_size = 1.0`
- both returned `market_status = EDITS_ONLY` on this demo account
- the market payload did not include `marginFactor`, `marginFactorUnit`, or `openingHours` in the fields currently parsed by Talim

On April 13, 2026, the new `IGPriceFeed` also verified:

- `/prices/{epic}?resolution=MINUTE_5&max=...` returns usable `5m` bars on the demo account
- `AU200.cash` bars can be fetched and written to Parquet via [ingest_ig_prices.py](../scripts/ingest_ig_prices.py:1)

Important consequence:

- `WP-49` is sufficient to proceed with the IG adapter work because the initial AU200 market ids are now known
- `WP-50` / `WP-52` still need to account for any missing contract metadata through either additional IG endpoints, documented IG product rules, or live/demo order validation

## Required Credentials

Set one of these auth paths:

1. Login credentials

```env
IG_API_KEY=
IG_IDENTIFIER=
IG_PASSWORD=
IG_ENVIRONMENT=demo
```

2. Pre-issued session tokens

```env
IG_API_KEY=
IG_CST=
IG_SECURITY_TOKEN=
IG_ENVIRONMENT=demo
```

Session tokens are useful if you want to avoid storing the password in the script environment.

## Discovery Workflow

Search the target market:

```bash
cd /path/to/talim
./.venv/bin/python scripts/ig_market_discovery.py --canonical-id AU200.cash --search-only --json
```

Fetch the first discovered market and print a registry-ready patch:

```bash
cd /path/to/talim
./.venv/bin/python scripts/ig_market_discovery.py --canonical-id AU200.cash --select 0 --json
```

Fetch a known epic directly:

```bash
cd /path/to/talim
./.venv/bin/python scripts/ig_market_discovery.py --canonical-id AU200.cash --epic YOUR_IG_EPIC --json
```

## What Must Be Verified Before WP-50

`WP-49` is complete enough to proceed once a real IG demo session confirms:

- the exact epic for the target `Australia 200` cash market
- whether a second canonical instrument should track an expiry-specific forward/futures CFD
- minimum deal size and size increment

Remaining unknowns to carry into implementation:

- margin factor and unit from the API surface Talim will actually use
- any instrument-specific constraints IG enforces only at order submission time
- whether the returned product semantics align with Talim's initial `netted` venue assumption

## Go / No-Go Criteria

Proceed with `IG` as Talim's first CFD adapter only if:

- demo API auth succeeds consistently
- a specific `Australia 200` tradable market can be discovered and fetched via REST
- the market metadata is sufficient to populate the unresolved registry fields
- the price feed path is available on the documented Lightstreamer/REST APIs without paid add-ons beyond normal trading access

Do not proceed to `WP-50` if:

- the required AU index market is unavailable on the account/API
- dealing rules are too incomplete to size and risk orders correctly
- the market semantics differ materially from the current canonical CFD contract
