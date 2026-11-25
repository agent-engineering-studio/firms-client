from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def away_from_the_developers_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Every test runs in an empty directory: a .env in the checkout must not leak in."""
    monkeypatch.chdir(tmp_path)
