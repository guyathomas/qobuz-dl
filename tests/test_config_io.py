"""Tests for the atomic config-write helper.

Token-bearing config files are sensitive — partial writes would corrupt
the only credentials store. These tests pin the temp-then-replace idiom
plus 0600 permissions on POSIX.
"""

import configparser
import io
import os
import stat

import pytest

from qobuz_dl._config_io import atomic_write_config


def _build_parser(**defaults):
    cp = configparser.ConfigParser()
    cp["DEFAULT"] = defaults
    return cp


def _list_tempfiles(directory):
    return [p for p in directory.iterdir() if p.name.startswith(".config-")]


def test_atomic_write_creates_file_and_writes_keys(tmp_path):
    target = tmp_path / "config.ini"
    parser = _build_parser(user_id="3394846", user_auth_token="t-xyz")

    atomic_write_config(str(target), parser)

    assert target.is_file()
    content = target.read_text(encoding="utf-8")
    assert "user_id = 3394846" in content
    assert "user_auth_token = t-xyz" in content


def test_atomic_write_preserves_existing_on_failure(tmp_path, monkeypatch):
    """If os.replace raises mid-flight, the original config must remain
    untouched and no orphan temp files should clutter the target dir.
    """
    target = tmp_path / "config.ini"
    target.write_text("[DEFAULT]\nuser_id = OLD_VALUE\n", encoding="utf-8")
    original = target.read_text(encoding="utf-8")

    parser = _build_parser(user_id="NEW_VALUE")

    def _boom(*_args, **_kwargs):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(os, "replace", _boom)

    with pytest.raises(OSError):
        atomic_write_config(str(target), parser)

    # Original is intact.
    assert target.read_text(encoding="utf-8") == original

    # No orphan temp file left behind in the directory.
    leftovers = [p for p in tmp_path.iterdir() if p != target]
    assert leftovers == [], f"orphan temp file(s): {leftovers}"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics")
def test_atomic_write_sets_0600_on_posix(tmp_path):
    target = tmp_path / "config.ini"
    parser = _build_parser(user_id="x", user_auth_token="y")

    atomic_write_config(str(target), parser)

    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_atomic_write_cleans_temp_when_parser_write_raises(tmp_path, monkeypatch):
    """If `parser.write(tmp)` blows up before we ever reach os.replace,
    the partially-written temp file must be unlinked and the original
    target file preserved.
    """
    target = tmp_path / "config.ini"
    target.write_text("[DEFAULT]\nuser_id = OLD\n", encoding="utf-8")

    class BoomParser:
        def write(self, fp):
            fp.write("partial...")  # write something to the temp file
            raise RuntimeError("simulated parser failure")

    with pytest.raises(RuntimeError, match="simulated parser failure"):
        atomic_write_config(str(target), BoomParser())

    assert target.read_text(encoding="utf-8") == "[DEFAULT]\nuser_id = OLD\n"
    assert _list_tempfiles(tmp_path) == []


def test_atomic_write_cleans_temp_when_fsync_raises(tmp_path, monkeypatch):
    """If `os.fsync(tmp.fileno())` raises (rare but possible on some
    filesystems / closed fds) the temp file must be unlinked and the
    target preserved.
    """
    target = tmp_path / "config.ini"
    target.write_text("[DEFAULT]\nuser_id = OLD\n", encoding="utf-8")

    real_fsync = os.fsync
    calls = {"n": 0}

    def selective_fsync(fd):
        calls["n"] += 1
        # First call is the temp-file fsync (the one we're targeting).
        if calls["n"] == 1:
            raise OSError("simulated fsync failure")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", selective_fsync)

    parser = _build_parser(user_id="NEW", user_auth_token="t")
    with pytest.raises(OSError, match="simulated fsync failure"):
        atomic_write_config(str(target), parser)

    assert target.read_text(encoding="utf-8") == "[DEFAULT]\nuser_id = OLD\n"
    assert _list_tempfiles(tmp_path) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX chmod semantics")
def test_atomic_write_chmod_failure_after_replace_does_not_corrupt(
    tmp_path, monkeypatch
):
    """If chmod fails after a successful os.replace, the new content is
    already in place. Pin the contract: the failure surfaces but the
    target file holds the new content (NOT the old one).

    Rationale: at this point we've already committed; the file mode is
    a hardening concern, not a correctness one.
    """
    target = tmp_path / "config.ini"
    target.write_text("[DEFAULT]\nuser_id = OLD\n", encoding="utf-8")

    def boom_chmod(_path, _mode):
        raise OSError("simulated chmod failure")

    monkeypatch.setattr(os, "chmod", boom_chmod)

    parser = _build_parser(user_id="NEW", user_auth_token="t")
    with pytest.raises(OSError, match="simulated chmod failure"):
        atomic_write_config(str(target), parser)

    # Replace already happened; the new content is durable.
    assert "user_id = NEW" in target.read_text(encoding="utf-8")
