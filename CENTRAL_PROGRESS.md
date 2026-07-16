# Central Progress Index

This is the shared index for agent-pickable Talim work.

Agents should read this before choosing idle/background work. When a new roadmap,
progress tracker, checklist, or planning markdown file is created for Talim,
append a row here in the same session.

## Status Legend

- `[ ]` Not started
- `[~]` In progress
- `[x]` Complete
- `[!]` Blocked / needs a decision

## Active Work Sources

| Area | File | Status | Agent pickup guidance | Last noted |
|------|------|--------|-----------------------|------------|
| Talim research/backtesting | `/home/wombat/openclaw-app/BACKTESTING_ROADMAP.md` | `[~]` | Use this for historical data, strategy research, comparison rules, indicators, assets, and backtest quality work. | 2026-07-12 |
| Talim reliability/safety | `/home/wombat/openclaw-app/RELIABILITY_ROADMAP.md` | `[~]` | Use this for backup, recovery, safe-write, resumption, and data-protection work. Respect blocked items and Justin decision gates. | 2026-07-12 |
| Talim product work packages | `PROGRESS.md` | `[~]` | Use this for concrete Talim implementation WPs. Prefer this when work has already been promoted from roadmap/research into a numbered WP. | 2026-07-12 |
| Indicator research batch 2 | `docs/indicator-research-batch-2.md` | `[~]` | Agent-pickable: implement items 1–4 (ADX/DMI, Keltner, SuperTrend, Efficiency Ratio) as library indicators + feature builders with parity tests — no market data or credentials needed. Do NOT run evaluation backtests until costed baselines exist and WP-87 is signed off; VWAP/OBV are gated on a volume-quality audit. | 2026-07-12 |

## Registration Rule

When creating any new progress/task/planning markdown file for Talim, append a
row to `Active Work Sources` with:

- the work area
- the file path
- current status
- how an idle agent should decide whether to pick work from it
- the current date

If the new file is temporary scratch, either avoid creating it or mark it as
temporary and remove/register the durable destination before ending the session.
