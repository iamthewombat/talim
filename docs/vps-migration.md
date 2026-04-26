# VPS Migration Runbook (WP-47)

Talim's stack is intentionally host-agnostic: every persistent piece of
state lives in a bind-mounted host directory, and every host-specific
value is in `.env`. Moving Talim to a VPS (or any second host) is
therefore a copy + start operation, not a re-deploy.

This runbook is the procedure.

## Persistent state on disk

After WP-47, the on-disk layout under the repo root is:

| host path     | container path | what's inside                                            |
|---------------|----------------|----------------------------------------------------------|
| `./state/`    | `/app/state/`  | `talim_checkpoints.db`, `episodic.db`, `backtest_history.db` |
| `./redis/`    | `/data/`       | Redis AOF + RDB                                          |
| `./backups/`  | `/app/backups/`| Output of `scripts/backup.sh`                            |
| `./data/`     | `/app/data/`   | Ingested OHLCV parquet (regenerable)                     |
| `./nginx/`    | (mounted ro)   | nginx config + (optional) TLS certs                      |
| `./config/`   | `/app/config/` | CFD registry, risk config (in image, can be overridden)  |

There are no named docker volumes. Anything outside these directories is
ephemeral (rebuildable from the image and `.env`).

## What's "the deployment"

A complete Talim deployment is exactly:

1. The `.env` file (secrets + host-specific overrides).
2. The bind-mounted state directories above (`./state`, `./redis`, `./backups`).
3. Optionally `./data/` (parquet history) — large but regenerable from
   `scripts/ingest_ig_prices.py` / `scripts/ingest_forexcom_prices.py`.
4. Optionally `./nginx/certs/` (TLS material) if you've enabled HTTPS.

Source code comes from `git pull`; the image rebuilds from the
`Dockerfile`. Nothing in the deployment depends on a specific host path.

## Migration procedure

### 1. Provision the new host

Tested target: Ubuntu 24.04 LTS on a VPS reachable via Tailscale.

```bash
# On the new host
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y docker.io docker-compose-plugin tailscale rsync git curl
sudo systemctl enable --now docker
sudo tailscale up
```

Lock down inbound access to the tailnet:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow in on tailscale0
sudo ufw enable
```

Do **not** publish ports `8080`/`8443` to `0.0.0.0` if you intend to
access Talim only over Tailscale — bind them to the tailnet IP in
`docker-compose.yml`, or front them with the existing nginx and access
via the tailnet hostname.

### 2. Pull the repo and prep the directories

```bash
sudo mkdir -p /opt/talim && sudo chown "$USER:$USER" /opt/talim
git clone https://github.com/<your-org>/talim.git /opt/talim
cd /opt/talim
mkdir -p state redis backups data
```

(The `.gitkeep` files mean these directories exist after `git clone`,
but `mkdir -p` is idempotent and explicit.)

### 3. Stop the old host (cleanly)

On the old host:

```bash
cd /path/to/talim
docker compose stop
```

Stopping (rather than `down`) keeps the redis AOF flushed and prevents
new writes during the copy.

### 4. Copy state + .env

From the old host:

```bash
rsync -av --delete state/   newhost:/opt/talim/state/
rsync -av --delete redis/   newhost:/opt/talim/redis/
rsync -av --delete backups/ newhost:/opt/talim/backups/
rsync -av           .env    newhost:/opt/talim/.env
# Optional: parquet history (large, regenerable)
rsync -av --delete data/    newhost:/opt/talim/data/
# Optional: TLS certs if you've enabled HTTPS
rsync -av --delete nginx/certs/ newhost:/opt/talim/nginx/certs/
```

Sanity-check the `.env`:

- `TALIM_BRIDGE_SECRET` is set.
- Broker creds match the environment you want (`IG_ENVIRONMENT=demo`
  unless you have explicit live sign-off).
- `OLLAMA_URL` either points at an LLM the new host can reach, or is
  left blank (Talim's notify path falls back to `"ack"` without an LLM).

### 5. Start the stack on the new host

```bash
cd /opt/talim
docker compose up -d --build
docker compose ps
```

`--build` rebuilds the image against the new host's architecture.

### 6. Verify

```bash
# 1. Container health (image-defined HEALTHCHECK)
docker inspect --format '{{.State.Health.Status}}' talim-app

# 2. Bridge health (no auth)
curl -fsS http://localhost:8080/talim/health
# {"status":"ok"}

# 3. Halt-status (no auth)
curl -fsS http://localhost:8080/talim/halt-status
# {"halted":false}

# 4. Authenticated runtime status
curl -fsS -H "X-Talim-Secret: $TALIM_BRIDGE_SECRET" \
  http://localhost:8080/talim/operator/status | jq .

# 5. Operator dashboard (browser)
#    open http://<tailscale-host>:8080/talim/dashboard/
```

Expected:

- `Health.Status` is `healthy` within ~30s.
- `/talim/halt-status` returns the same `halted` flag the old host had
  (the flag is in-process so a restart resets it to `false` — set it
  again with `POST /talim/halt` if you were halted at migration time).
- `/talim/operator/status` returns the same active strategies and
  instruments (read from `.env`) and the same `account_balance` /
  `position_count` (read from the broker, not from local state).
- `/talim/operator/decisions` returns the historical decisions from the
  copied `episodic.db`.
- `/talim/operator/backtests` returns the historical runs from the
  copied `backtest_history.db`.

### 7. Switch clients

Whatever pointed at the old host (OpenClaw, the dashboard, your
scheduler trigger) needs to repoint at the new host's URL or tailnet
hostname. There's no central registry — it's just `TALIM_BRIDGE_URL` in
each client.

### 7a. Same-Host OpenClaw Cutover

If OpenClaw is already running on the target host, finish the cutover by
pointing it at Talim's same-host private URL:

```text
http://127.0.0.1:8080/talim
```

Use a Tailscale or other private hostname only if OpenClaw cannot reach
localhost from its own runtime context.

Before enabling `IG demo` in Talim:

- validate authenticated `GET /talim/operator/status`
- validate authenticated `POST /talim/sync?thread_id=cron-main`
- confirm OpenClaw can read pending HITL state and send approve/reject

OpenClaw state/config migration is separate from Talim state migration. This
runbook moves Talim's repo, state, and env; it does not move OpenClaw's own
database, config, or secrets for you.

### 8. Decommission the old host

Once steady-state on the new host is confirmed (give it at least one
full trading session), shut down the old stack:

```bash
# On the old host
docker compose down
```

Keep the old `state/` directory archived for a week as a rollback
escape hatch before reformatting the host.

## Rollback

If the new host is unhealthy, the old host's `state/` is still intact
(you only ran `docker compose stop`, not `down`). Bring it back up:

```bash
# On the old host
docker compose up -d
```

Then debug the new host without time pressure.

## Restore from `scripts/backup.sh` output

If a corruption event forces you to restore from `backups/` rather than
`state/`:

```bash
docker compose stop talim
ls -1t backups/episodic-*.db | head -1   # newest
cp backups/episodic-<timestamp>.db state/episodic.db
cp backups/talim_checkpoints-<timestamp>.db state/talim_checkpoints.db
cp backups/backtest_history-<timestamp>.db state/backtest_history.db
docker compose up -d talim
```

`scripts/backup.sh` writes `<dbname>-<timestamp>.db` files into the
`./backups/` bind mount. The compose `talim` and `scheduler` services
both bind `./backups`, so you can also run the restore step from inside
the container if you prefer.

## Anti-patterns

- **Re-introducing named volumes.** Never replace `./state` /
  `./redis` / `./backups` with `volumes:` named volumes. Named volumes
  break this runbook because they live in `/var/lib/docker` on the host
  and don't move via `rsync`.
- **Hardcoded host paths in docs/scripts.** Use `/path/to/talim` or
  `$TALIM_REPO` rather than your laptop's home directory.
- **Pinning to `host.docker.internal`** on Linux. That hostname only
  resolves inside Docker Desktop (Mac/Windows). On a Linux VPS, point
  `OLLAMA_URL` at the actual gateway address or use `network_mode:
  host` for the Ollama side.

## Cross-references

- `docs/laptop-setup.md` — initial laptop install (refers here for the
  bind-mount layout).
- `docs/disaster-recovery.md` — backup/restore procedures.
- `docs/operator-dashboard.md` — once the bridge is healthy, the
  dashboard is at `/talim/dashboard/` on the same host.
