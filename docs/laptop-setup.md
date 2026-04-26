# Laptop Setup Checklist

This runbook is for the current local-first plan:

- fresh Ubuntu laptop
- home Wi-Fi
- `OpenClaw` as the private interface layer
- `Talim` running locally with Docker
- no public exposure
- `IG` demo first, live later

This is intentionally a checklist, not a design doc.

## 1. Install Ubuntu

- [ ] Install `Ubuntu 24.04 LTS`
- [ ] Enable full-disk encryption during install
- [ ] Keep Secure Boot enabled
- [ ] Use a strong local account password
- [ ] Disable auto-login
- [ ] Give the machine a clear hostname, for example `talim-laptop`
- [ ] Join the home Wi-Fi network

Optional but sensible:

- [ ] Set a BIOS/UEFI admin password
- [ ] Disable boot from USB unless needed

## 2. First Boot Hardening

- [ ] Update the OS and reboot

```bash
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

- [ ] Install base packages

```bash
sudo apt install -y \
  ufw \
  unattended-upgrades \
  git \
  curl \
  ca-certificates \
  docker.io \
  docker-compose-plugin
```

- [ ] Enable automatic security updates

```bash
sudo dpkg-reconfigure -plow unattended-upgrades
```

- [ ] Enable the firewall with default-deny inbound

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw enable
sudo ufw status verbose
```

- [ ] Do not configure router port forwarding
- [ ] Do not expose Redis, Grafana, OpenClaw, or Talim directly to the public internet

## 3. Laptop Reliability Settings

- [ ] Disable suspend/sleep while plugged in
- [ ] Disable suspend on lid close if this machine will run with the lid shut
- [ ] Keep the laptop plugged into power when Talim is running
- [ ] Confirm the Wi-Fi connection is stable where the laptop will sit
- [ ] Turn on screen lock for local physical security

Example systemd approach for a dedicated machine:

```bash
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
```

If you still use the laptop interactively, prefer GNOME power settings instead of masking sleep globally.

## 4. Private Access

- [ ] Install Tailscale
- [ ] Authenticate the laptop into your tailnet
- [ ] Use Tailscale for any remote admin access
- [ ] Keep admin access private; do not rely on public ports

If you want remote shell access:

- [ ] Install `openssh-server`
- [ ] Use it only over Tailscale

```bash
sudo apt install -y openssh-server
sudo ufw allow OpenSSH
```

## 5. OpenClaw

- [ ] Install `OpenClaw` using its Ansible production path
- [ ] Keep the gateway bound to loopback or Tailscale-only
- [ ] Keep auth enabled
- [ ] Keep sandboxing enabled
- [ ] Do not expose the OpenClaw UI publicly
- [ ] Record where the OpenClaw state/config lives on disk

Operational checks:

- [ ] OpenClaw starts cleanly after reboot
- [ ] OpenClaw is reachable from your admin device over Tailscale
- [ ] OpenClaw is not reachable from the public internet

## 6. Talim

- [ ] Clone the repo onto the laptop
- [ ] Create `.env` from `.env.example`
- [ ] Set `TALIM_BRIDGE_SECRET`
- [ ] Add any LLM keys you actually plan to use
- [ ] Add IG demo credentials
- [ ] Start the local stack

```bash
cd /path/to/talim
docker compose up -d
docker compose ps
```

Minimum env items to check:

- [ ] `TALIM_BRIDGE_SECRET`
- [ ] `IG_DEMO_API_KEY` or `IG_API_KEY`
- [ ] `IG_DEMO_LOGIN` / `IG_DEMO_PASSWORD` or `IG_IDENTIFIER` / `IG_PASSWORD`
- [ ] `IG_ENVIRONMENT=demo`

Useful verification commands:

```bash
cd /path/to/talim
./.venv/bin/python -m pytest -q \
  tests/test_ig_exchange.py \
  tests/test_exchange_factory.py \
  tests/test_ig_discovery.py \
  tests/test_cfd_registry.py
```

```bash
cd /path/to/talim
./.venv/bin/python scripts/ig_market_discovery.py --canonical-id AU200.cash --json
```

## 7. Current IG AU200 Mapping

These are the currently resolved demo mappings in the repo:

- `AU200.cash` -> `IX.D.ASX.IFT.IP`
- `AU200.fwd` -> `IX.D.ASX.FWM2.IP`

Current caveats:

- demo discovery returned `EDITS_ONLY` for both instruments on the current account
- more CFD-specific risk/P&L/session work is still pending
- IG price feed and historical ingestion are now implemented, but still need to be wired into your full runtime config on the laptop

See:

- [exchange-setup.md](../docs/exchange-setup.md)
- [ig-cfd-feasibility.md](../docs/ig-cfd-feasibility.md)

## 8. Backups

- [ ] Enable Talim backups with [scripts/backup.sh](../scripts/backup.sh)
- [ ] Back up the Talim repo `.env` securely
- [ ] Back up Talim state/data directories
- [ ] Back up OpenClaw state/config
- [ ] Keep at least one encrypted copy off the laptop
- [ ] Test restore at least once

> Talim's persistent state lives in bind-mounted host directories
> (`./state`, `./redis`, `./backups`) — see
> [vps-migration.md](vps-migration.md) for the full layout and the
> procedure for moving the deployment to a different host.

## 9. Sign-Off Before Long-Running Demo Use

- [ ] Laptop survives reboot and both OpenClaw and Talim come back cleanly
- [ ] Laptop does not sleep when plugged in
- [ ] Tailscale access works
- [ ] OpenClaw is private-only
- [ ] Talim stack is up and healthy
- [ ] IG discovery works from the laptop
- [ ] Docker services restart cleanly
- [ ] Backup job works
- [ ] No router port forwarding exists
- [ ] Demo only, not live capital

## 10. Not Done Yet In Repo

These are still the next build steps:

- [x] `WP-52` CFD risk, P&L, and session model
- [x] `WP-53` AU200 strategy validation and IG demo soak

This laptop is still a private development and demo box, not a production trading host.
