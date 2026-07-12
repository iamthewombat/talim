# Polymarket Feasibility, Compliance, and Product-Fit Gate (WP-54)

> Status: research complete 2026-07-12. **Recommendation: NO-GO for the
> Australian jurisdiction.** Blocked on Justin's decision to close or park
> Phase 11 (WP-54–WP-58). No connector work (WP-55+) should start unless the
> facts below change.

## The gate question

WP-54 exists to answer one question before any Polymarket connector is
built: *is Polymarket usable for the intended jurisdiction (Australia) and
use case (automated event-market trading by Talim)?*

## Findings

### 1. Polymarket is a prohibited service in Australia (decisive)

- In **July 2025** the Australian Communications and Media Authority issued
  a **formal warning to Adventure One QSS Inc. (Polymarket)** for providing
  an unlicensed interactive gambling service to Australians (signed warning
  published on acma.gov.au).
- In **August 2025** the ACMA directed Australian ISPs to **block
  Polymarket** as a prohibited service under the **Interactive Gambling Act
  2001**. This is a regulator-ordered ISP-level block, not merely
  Polymarket's own geofencing.
- The enforcement was triggered by Polymarket promoting Australian federal
  election markets to Australian audiences through paid social-media
  influencers (April 2025 reporting).
- Polymarket's own terms and geo-restrictions also list Australia as a
  restricted jurisdiction; access from Australia would require deliberate
  circumvention (VPN), breaching both Polymarket's ToS and the intent of an
  ACMA blocking direction.

### 2. Automation makes it worse, not better

Talim is an automated system operating on behalf of an Australian operator.
Building a connector would mean programmatically circumventing a
regulator-ordered block to place wagers on an unlicensed gambling service —
with wallet funds exposed on a platform that can freeze or geo-restrict the
account at any time. This is not a grey area worth engineering around.

### 3. Product fit is poor even ignoring compliance (secondary)

- Polymarket is a wallet-authenticated CLOB on Polygon settling in USDC:
  custody, signing, and funding models Talim does not have today
  (acknowledged in the WP-55/WP-57 scopes).
- Event contracts are capped-payout binary instruments driven by
  probability, news flow, and resolution rules — not OHLCV bars. WP-57/WP-58
  were scoped precisely because almost none of the existing regime/strategy/
  risk/backtest stack transfers.
- Polymarket's 2025 US re-entry via a CFTC-regulated exchange acquisition is
  a US-persons path and does nothing for Australian access.

## Recommendation

1. **Close Phase 11 (WP-54–WP-58) as won't-do** for the current operator
   jurisdiction, or park it with an explicit re-open condition ("ACMA
   position changes or Polymarket obtains an Australian licence" — neither
   is plausible near-term). Closing is recommended: a parked phase invites
   idle-agent work on a dead end.
2. If event-market exposure remains interesting, the compliant route is an
   **Australian-licensed operator** (e.g. an NT-licensed exchange such as
   Betfair Australia). That would be a new feasibility WP with its own
   product-fit analysis — do not inherit the Polymarket WP numbers.

## Decision needed from Justin

- [ ] Close WP-54–WP-58 (recommended), or
- [ ] Park Phase 11 with the re-open condition stated above, or
- [ ] Open a new feasibility WP for an Australian-licensed event-market
      venue.

## Sources

Primary (surfaced via search; acma.gov.au blocks automated fetching, so
verify in a browser):

- ACMA formal warning PDF: `acma.gov.au/sites/default/files/2025-08/02.07.2025 - Formal Warning - Adventure One QSS Inc. - Polymarket SIGNED_Redacted.pdf`
- ACMA, "Latest illegal online gambling websites blocked" (August 2025)
- ACMA, "Action on interactive gambling: July to September 2025"
- Polymarket Help Center / API docs, "Geographic Restrictions"

Secondary reporting: Covers, "Australia Bans Polymarket Over Gambling Law
Breach" (Aug 2025); CasinoBeats, "Polymarket Blocked In Australia For
Targeting Users Through Social Media" (Aug 2025); NEXT.io, "Polymarket
banned by Australian media regulator" (Aug 2025).
