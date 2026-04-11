"""Markdown strategy file store — read, write, and list strategy documents."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("talim.strategy.store")


# Default strategies directory
_STRATEGIES_DIR = Path(__file__).resolve().parent.parent.parent / "strategies"


class StrategyStore:
    """Read and write strategy markdown files in the strategies/ directory."""

    def __init__(
        self,
        strategies_dir: Path | None = None,
        git_enabled: bool = False,
    ):
        self._dir = strategies_dir or _STRATEGIES_DIR
        self.git_enabled = git_enabled

    def read(self, name: str) -> str:
        """Read a strategy's markdown file.

        Looks for strategies/{name}/{name}.md
        """
        md_path = self._dir / name / f"{name}.md"
        if not md_path.exists():
            raise FileNotFoundError(f"Strategy markdown not found: {md_path}")
        return md_path.read_text()

    def write(self, name: str, content: str) -> None:
        """Write (or overwrite) a strategy's markdown file."""
        strategy_dir = self._dir / name
        strategy_dir.mkdir(parents=True, exist_ok=True)
        md_path = strategy_dir / f"{name}.md"
        md_path.write_text(content)

    def commit_change(self, name: str, message: str) -> bool:
        """Commit the strategy markdown file to git (WP-25).

        Returns True on success, False if git is disabled or the commit
        could not be created (e.g. not a git repo, nothing changed).
        """
        if not self.git_enabled:
            return False
        md_path = self._dir / name / f"{name}.md"
        if not md_path.exists():
            return False
        try:
            subprocess.run(
                ["git", "-C", str(self._dir), "add", str(md_path)],
                check=True,
                capture_output=True,
            )
            result = subprocess.run(
                ["git", "-C", str(self._dir), "commit", "-m", message],
                capture_output=True,
            )
            if result.returncode != 0:
                logger.info(
                    "commit_change: git commit returned %d (%s)",
                    result.returncode,
                    result.stderr.decode(errors="replace").strip(),
                )
                return False
            return True
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.warning("commit_change: git operation failed: %s", e)
            return False

    def list_strategies(self) -> list[str]:
        """List all strategy names that have a markdown file."""
        if not self._dir.exists():
            return []
        names = []
        for d in sorted(self._dir.iterdir()):
            if d.is_dir() and (d / f"{d.name}.md").exists():
                names.append(d.name)
        return names
