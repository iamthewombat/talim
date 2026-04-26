"""Smoke tests for the WP-18 deployment files (no Docker daemon required)."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _read(p: str) -> str:
    return (ROOT / p).read_text()


class TestDeploymentFiles:
    def test_dockerfile_exists(self):
        assert (ROOT / "Dockerfile").exists()
        body = _read("Dockerfile")
        assert "FROM python" in body
        assert "uvicorn" in body
        assert "EXPOSE 8000" in body

    def test_compose_has_required_services(self):
        body = _read("docker-compose.yml")
        for svc in ("redis:", "talim:", "scheduler:", "nginx:"):
            assert svc in body, f"missing service {svc}"

    def test_compose_uses_bridge_secret(self):
        assert "TALIM_BRIDGE_SECRET" in _read("docker-compose.yml")

    def test_nginx_config_proxies_bridge(self):
        body = _read("nginx/nginx.conf")
        assert "talim:8000" in body
        assert "/talim/" in body

    def test_env_example(self):
        body = _read(".env.example")
        assert "TALIM_BRIDGE_SECRET" in body
        assert "ANTHROPIC_API_KEY" in body

    def test_healthcheck_script(self):
        path = ROOT / "scripts" / "healthcheck.sh"
        assert path.exists()
        # Executable bit set.
        assert path.stat().st_mode & 0o111

    def test_cron_config(self):
        body = _read("scripts/cron.txt")
        assert "*/5" in body  # heartbeat
        assert "/talim/sync" in body  # broker state reconciliation
