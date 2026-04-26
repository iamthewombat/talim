# OpenClaw Host Cutover Checklist

Use this when the repo is on the OpenClaw host and you're ready to bring Talim
up there.

## 1. Host Prerequisites

- [ ] Docker and Docker Compose plugin installed
- [ ] Repo cloned onto the host
- [ ] `.env` created and populated
- [ ] Private access path in place (`localhost`, LAN, or Tailscale)
- [ ] No public exposure planned for Talim or OpenClaw

## 2. Talim Bring-Up

- [ ] `docker compose up -d --build`
- [ ] `docker compose ps`
- [ ] `GET /talim/health` succeeds
- [ ] `GET /talim/halt-status` succeeds

Reference commands:

```bash
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:8080/talim/health
curl -fsS http://127.0.0.1:8080/talim/halt-status
```

## 3. OpenClaw ↔ Talim Auth Validation

- [ ] `TALIM_BRIDGE_SECRET` stored in Talim
- [ ] matching secret stored in OpenClaw
- [ ] authenticated `GET /talim/operator/status` succeeds
- [ ] authenticated `POST /talim/sync?thread_id=cron-main` succeeds

Reference commands:

```bash
curl -fsS -H "X-Talim-Secret: $TALIM_BRIDGE_SECRET" \
  http://127.0.0.1:8080/talim/operator/status

curl -fsS -X POST -H "X-Talim-Secret: $TALIM_BRIDGE_SECRET" \
  http://127.0.0.1:8080/talim/sync?thread_id=cron-main
```

## 4. Mock Integration Gate

- [ ] Talim starts in `mock` mode first
- [ ] OpenClaw can read runtime status
- [ ] OpenClaw can refresh broker/runtime state with `/talim/sync`
- [ ] pending signal is visible through `/talim/operator/pending`
- [ ] approve/reject works through `/talim/operator/decision`
- [ ] decisions update after approval/rejection
- [ ] positions update after approval

## 5. IG Demo Gate

- [ ] Talim switched to `IG demo`
- [ ] IG auth works on the host
- [ ] feed is connected
- [ ] one smallest protected demo trade is approved from OpenClaw
- [ ] broker UI confirms the order and attached protection
- [ ] `/talim/operator/positions` reflects the open position
- [ ] `/talim/operator/decisions` reflects the approved decision
- [ ] `/talim/sync?thread_id=cron-main` shows no unexplained drift

## 6. Fallback / Debug

- [ ] Talim dashboard is reachable at `/talim/dashboard/`
- [ ] dashboard can be used if OpenClaw behavior and Talim state disagree

## 7. Rollback

- [ ] If the host stack is unhealthy, stop before demo trading
- [ ] Revert to the pre-move Talim environment/state rather than debugging
      against an active broker session
- [ ] Do not leave the IG demo runtime enabled until the mock gate and auth
      gate are both green
