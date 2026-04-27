"""Tests for `--show-config` redaction.

`config.ini` is now stored at 0600, but users still copy/paste its
contents into bug reports, screenshots, and logs. Default `--show-config`
output redacts every secret-bearing key (`user_auth_token`, `secrets`,
legacy `password`). `--show-secrets` opt-in reveals the raw values.

`app_id` is NOT redacted: it's a public constant embedded in
`bundle.js` and visible to anyone who opens DevTools.
"""

import configparser
from unittest.mock import patch

import pytest

from qobuz_dl import cli


def _write_config(path, **fields):
    parser = configparser.ConfigParser()
    parser["DEFAULT"] = {
        "default_folder": "Qobuz Downloads",
        "default_quality": "6",
        "default_limit": "20",
        "no_m3u": "false",
        "albums_only": "false",
        "no_fallback": "false",
        "og_cover": "false",
        "embed_art": "false",
        "no_cover": "false",
        "no_database": "false",
        "app_id": "798273057",
        "secrets": "secretA,secretB",
        "smart_discography": "false",
        "folder_format": "{artist} - {album}",
        "track_format": "{tracknumber}. {tracktitle}",
        **fields,
    }
    with open(path, "w", encoding="utf-8") as f:
        parser.write(f)


def _setup(monkeypatch, tmp_path, **config_fields):
    config_dir = tmp_path / "qobuz-dl"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.ini"
    monkeypatch.setattr(cli, "CONFIG_PATH", str(config_dir))
    monkeypatch.setattr(cli, "CONFIG_FILE", str(config_file))
    monkeypatch.setattr(cli, "QOBUZ_DB", str(config_dir / "qobuz.db"))
    _write_config(str(config_file), **config_fields)
    return str(config_file)


def test_show_config_redacts_user_auth_token_and_secrets_by_default(
    tmp_path, monkeypatch, capsys
):
    _setup(
        monkeypatch,
        tmp_path,
        user_id="3394846",
        user_auth_token="ABC-VERY-SECRET-TOKEN-123",
    )
    monkeypatch.setattr("sys.argv", ["qobuz-dl", "--show-config"])

    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out

    assert "ABC-VERY-SECRET-TOKEN-123" not in out
    assert "secretA" not in out
    assert "secretB" not in out
    assert "***REDACTED***" in out
    # app_id should NOT be redacted (public constant in bundle.js)
    assert "798273057" in out


def test_show_config_redacts_legacy_password_if_present(tmp_path, monkeypatch, capsys):
    _setup(
        monkeypatch,
        tmp_path,
        user_id="3394846",
        user_auth_token="t",
        email="user@example.com",
        password="0123456789abcdef0123456789abcdef",  # md5-shaped
    )
    monkeypatch.setattr("sys.argv", ["qobuz-dl", "--show-config"])

    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out

    assert "0123456789abcdef0123456789abcdef" not in out
    # email is not a secret per se but is PII; we don't require redaction
    # of it here. Re-check if/when we make a stronger claim.


def test_show_config_redacts_multiline_continuation_values(
    tmp_path, monkeypatch, capsys
):
    """`configparser` allows values to span multiple lines via leading
    whitespace continuation. A regex-only redactor would only cover the
    first line; the round-trip approach must replace the entire value.
    """
    config_dir = tmp_path / "qobuz-dl"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.ini"
    monkeypatch.setattr(cli, "CONFIG_PATH", str(config_dir))
    monkeypatch.setattr(cli, "CONFIG_FILE", str(config_file))
    monkeypatch.setattr(cli, "QOBUZ_DB", str(config_dir / "qobuz.db"))

    # Hand-rolled INI with a continuation-line user_auth_token.
    config_file.write_text(
        "[DEFAULT]\n"
        "user_id = 3394846\n"
        "user_auth_token = LINE1-PART-OF-SECRET\n"
        "    LINE2-CONTINUATION-OF-SECRET\n"
        "default_folder = Qobuz Downloads\n"
        "default_quality = 6\n"
        "default_limit = 20\n"
        "no_m3u = false\n"
        "albums_only = false\n"
        "no_fallback = false\n"
        "og_cover = false\n"
        "embed_art = false\n"
        "no_cover = false\n"
        "no_database = false\n"
        "app_id = 798273057\n"
        "secrets = secretA,secretB\n"
        "smart_discography = false\n"
        "folder_format = {artist} - {album}\n"
        "track_format = {tracknumber}. {tracktitle}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["qobuz-dl", "--show-config"])

    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out

    assert "LINE1-PART-OF-SECRET" not in out
    assert "LINE2-CONTINUATION-OF-SECRET" not in out
    assert "***REDACTED***" in out


def test_show_config_redacts_does_not_overmatch_benign_text(
    tmp_path, monkeypatch, capsys
):
    """A benign value containing the literal word 'password' (e.g. a
    folder name) must NOT be redacted — only values of keys named
    user_auth_token / secrets / password.
    """
    _setup(
        monkeypatch,
        tmp_path,
        user_id="3394846",
        user_auth_token="t",
        default_folder="Password Album Greatest Hits",
    )
    monkeypatch.setattr("sys.argv", ["qobuz-dl", "--show-config"])

    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out

    assert "Password Album Greatest Hits" in out


def test_show_secrets_flag_reveals_all(tmp_path, monkeypatch, capsys):
    _setup(
        monkeypatch,
        tmp_path,
        user_id="3394846",
        user_auth_token="ABC-VERY-SECRET-TOKEN-123",
    )
    monkeypatch.setattr("sys.argv", ["qobuz-dl", "--show-config", "--show-secrets"])

    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out

    assert "ABC-VERY-SECRET-TOKEN-123" in out
    assert "secretA" in out
    assert "secretB" in out
    assert "***REDACTED***" not in out
