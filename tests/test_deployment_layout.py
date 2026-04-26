"""Portability tests for the docker-compose deployment layout (WP-47).

These tests are static — they parse `docker-compose.yml` and assert that
the file matches the bind-mount-only contract documented in
`docs/vps-migration.md`. A future engineer who reintroduces a named
volume will see this test fail before they can ship the regression.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text())


def _service_volumes(compose: dict, name: str) -> list[str]:
    return list(compose["services"][name].get("volumes", []))


class TestNoNamedVolumes:
    """The deployment must not declare named volumes for runtime state."""

    def test_no_top_level_volumes_block(self, compose):
        # `volumes:` at the top level declares named volumes.
        # Bind mounts are inline on each service and don't need this block.
        # Allow it to be missing or explicitly empty/None.
        top = compose.get("volumes")
        assert top in (None, {}, []), (
            "docker-compose.yml declares named volumes at the top level. "
            "Bind-mount the host directory directly (./state, ./redis, "
            "./backups) — named volumes break the WP-47 migration runbook."
        )

    @pytest.mark.parametrize("service", ["talim", "redis", "scheduler"])
    def test_state_paths_are_bind_mounts(self, compose, service):
        for entry in _service_volumes(compose, service):
            # Bind mounts start with `./` or `/`; named volumes are bare names.
            source = entry.split(":", 1)[0]
            assert source.startswith(("./", "/")), (
                f"Service {service!r} declares non-bind-mount volume "
                f"{entry!r}. Use a bind mount instead."
            )


class TestRequiredBindMounts:
    """The bind mounts WP-47 promises must actually be present."""

    def test_talim_state_bind_mount(self, compose):
        vols = _service_volumes(compose, "talim")
        assert any(v.startswith("./state:") for v in vols), (
            "talim service must bind-mount ./state to the container's state dir"
        )

    def test_talim_backups_bind_mount(self, compose):
        vols = _service_volumes(compose, "talim")
        assert any(v.startswith("./backups:") for v in vols), (
            "talim service must bind-mount ./backups for backup script output"
        )

    def test_redis_data_bind_mount(self, compose):
        vols = _service_volumes(compose, "redis")
        assert any(v.startswith("./redis:") for v in vols), (
            "redis service must bind-mount ./redis to /data"
        )

    def test_scheduler_state_bind_mount(self, compose):
        vols = _service_volumes(compose, "scheduler")
        assert any(v.startswith("./state:") for v in vols), (
            "scheduler must see ./state to run backup.sh against live DBs"
        )


class TestStateDirectoriesExist:
    """The bind-mount source dirs must exist in the repo so docker compose
    starts cleanly on a fresh clone."""

    @pytest.mark.parametrize("rel", ["state", "redis", "backups", "data"])
    def test_directory_exists(self, rel):
        path = REPO_ROOT / rel
        assert path.is_dir(), f"missing host bind-mount source: {rel}/"

    @pytest.mark.parametrize("rel", ["state", "redis", "backups"])
    def test_gitkeep_present(self, rel):
        # Without .gitkeep, an empty directory disappears on git clone and
        # docker compose fails to start because the bind source is missing.
        path = REPO_ROOT / rel / ".gitkeep"
        assert path.exists(), (
            f"{rel}/.gitkeep is missing — fresh clones won't have the dir, "
            f"and docker compose will fail to bind-mount it."
        )


class TestEnvExampleCompleteness:
    """The .env.example must cover the env vars the compose file references
    so an operator on a new host has a complete checklist."""

    def test_state_env_vars_documented(self):
        env = (REPO_ROOT / ".env.example").read_text()
        for key in (
            "TALIM_BRIDGE_SECRET",
            "TALIM_CHECKPOINT_DB",
            "TALIM_EPISODIC_DB",
            "TALIM_BACKTEST_HISTORY_DB",
        ):
            assert key in env, f".env.example is missing {key}"
