import os
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def bundle_snippet() -> str:
    return (FIXTURES_DIR / "bundle.js.snippet").read_text(encoding="utf-8")


@pytest.fixture
def tmp_config_dir(tmp_path, monkeypatch):
    """Redirect ~/.config/qobuz-dl (or %APPDATA%/qobuz-dl) into a tmp_path."""
    fake_home = tmp_path / "config-root"
    fake_home.mkdir()
    if os.name == "nt":
        monkeypatch.setenv("APPDATA", str(fake_home))
    else:
        monkeypatch.setenv("HOME", str(fake_home))
    return fake_home
