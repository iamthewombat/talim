# Operator Monitoring Dashboard (WP-69)

A single-page HTML/JS dashboard that surfaces the Talim operator
endpoints in one view: runtime status, open positions + daily P&L,
pending HITL signal (with approve/reject), recent episodic decisions
(filterable), backtest run history (with drill-in), and strategy
on/off toggles.

The dashboard is served as static assets by the bridge FastAPI app.
No build step — the browser loads `index.html`, `app.js`, and
`style.css` directly.

This dashboard is the fallback/manual Talim console. For routine operation on a
same-host OpenClaw deployment, prefer the OpenClaw-native flow and keep the
dashboard available for debugging and parity checks.

## Routes

| path                              | auth                                   | description                               |
|-----------------------------------|----------------------------------------|-------------------------------------------|
| `GET /talim/dashboard/`           | none (HTML shell)                      | Dashboard page.                           |
| `GET /talim/dashboard/app.js`     | none                                   | Client-side logic.                        |
| `GET /talim/dashboard/style.css`  | none                                   | Styling.                                  |
| `GET /talim/operator/*`           | `X-Talim-Secret: $TALIM_BRIDGE_SECRET` | Read endpoints the dashboard consumes.    |
| `POST /talim/operator/decision`   | `X-Talim-Secret`                       | Approve/reject pending HITL signal.       |
| `POST /talim/halt`, `/resume-trading` | `X-Talim-Secret`                  | Kill switch.                              |
| `POST /talim/operator/strategies/{name}/enable|disable` | `X-Talim-Secret` | Toggle strategy active set.   |

The HTML shell itself is unauthenticated so the page can load before
the operator pastes the secret. Every data-bearing request the JS
makes carries `X-Talim-Secret`, which is stored in `sessionStorage`
and wiped on tab close.

## Auth model

Two explicit steps before the dashboard will perform any write:

1. **Set secret.** Click *Set secret* in the header and paste the
   bridge shared secret (`TALIM_BRIDGE_SECRET`). This unlocks reads.
2. **Unlock writes.** Click *Unlock writes* to arm approve/reject,
   halt, and strategy toggles for the current page load.

The unlocked-writes flag lives in memory only — a browser refresh
resets back to read-only. The secret in `sessionStorage` survives
refreshes but is cleared when the tab closes (or via the *Lock*
button).

## Running locally

```bash
export TALIM_BRIDGE_SECRET=<your-secret>
.venv/bin/uvicorn talim.api.bridge:create_app --factory --port 8000
```

Open <http://localhost:8000/talim/dashboard/> and paste
`$TALIM_BRIDGE_SECRET` when prompted.

## Running via docker-compose

The bridge container already exposes port 8000 and nginx proxies
`/talim/` → `talim:8000`, so the dashboard is reachable at:

- `http://<host>/talim/dashboard/` (plain HTTP via nginx)
- `https://<host>/talim/dashboard/` (once certs are mounted and the
  TLS `server` block in `nginx/nginx.conf` is uncommented)

`docker compose up nginx talim` is the minimum set of services. No
nginx config change was needed — the existing `location /talim/`
rule covers both the API and the dashboard.

If OpenClaw and Talim are on the same host, keep this dashboard reachable even
after OpenClaw is wired in. It is the fastest way to check whether an issue is
in Talim itself or only in the OpenClaw integration layer.

## Panels

- **Runtime** — exchange name/mode, pricefeed state and subscriptions,
  active instruments + strategies, open P&L, daily P&L, account
  balance, halt status + HALT/Resume button (write-gated).
- **Pending HITL** — the pending signal on `thread_id=cron-main`,
  including its durable `signal_id` and advisory validation status when
  present, with Approve/Reject buttons (write-gated). POSTs to
  `/talim/operator/decision`.
  Links of the form `/talim/dashboard/signal.html?signal=<signal_id>` open the
  mobile-friendly standalone HITL signal page with the durable signal row,
  original signal, latest validation fields, live pending validation when it is
  still current, and approve/reject controls. Approve is disabled unless the
  linked signal is the current pending signal and live validation allows
  approval; stale/non-current links show a warning. The operator page still
  shows compact pending-signal information and links out to this page.
- **Open Positions** — live broker positions with per-position
  open P&L.
- **Strategies** — all loadable strategies under `strategies/`, with
  an Enable/Disable button per row (write-gated). Calls
  `/talim/operator/strategies/{name}/enable|disable`.
- **Recent Decisions** — episodic decisions table, filterable by
  instrument, strategy, and limit.
- **Backtest History** — persistent runs from the WP-68 history store,
  filterable by strategy/instrument. Clicking a row opens a detail
  view with parameter variant, matched dates, and full metrics.

All panels auto-refresh every 15 seconds; the *Refresh* button in
the header triggers an immediate refresh of every panel.

## Extending

- New panel: add a `<section class="panel">` to `index.html`, a
  `refreshX()` function to `app.js`, and wire it into `refreshAll()`.
- New operator endpoint: add the route to `talim/api/bridge.py`
  behind `Depends(require_secret)` and surface it from the JS via
  the `api()` helper (it injects the secret header automatically).
- Client-side helpers live in `talim/api/static/app.js`; there is
  no bundler — edits are live after a page refresh.

## Smoke tests

`tests/test_bridge.py::TestOperatorDashboard` covers:

- `GET /talim/dashboard/` serves HTML including the dashboard title.
- `GET /talim/dashboard` (no trailing slash) also resolves.
- `app.js` and `style.css` are served with correct content types.
- The HTML shell is public, but `/talim/operator/*` still 401s
  without a valid `X-Talim-Secret` — the dashboard cannot bypass
  bridge auth.

Run with:

```bash
.venv/bin/python -m pytest tests/test_bridge.py::TestOperatorDashboard -v
```
