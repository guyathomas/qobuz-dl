"""Tests for `qobuz_dl.cli.main` dispatch precedence.

Dispatch table (top-down):
  (a) --reset                       -> run reset
  (b) no config file                -> run reset interactively
  (c) user_id + user_auth_token     -> initialize_client_with_token
  (d) email/password keys but no token -> exit(2) with migration message
  (e) corrupt/unparseable config    -> exit(2) with --reset pointer
  (f) no credentials at all         -> exit(2) with capture instructions
"""

import configparser
from unittest.mock import MagicMock, patch

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


def _patch_cli_paths(monkeypatch, tmp_path):
    config_dir = tmp_path / "qobuz-dl"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.ini"
    monkeypatch.setattr(cli, "CONFIG_PATH", str(config_dir))
    monkeypatch.setattr(cli, "CONFIG_FILE", str(config_file))
    monkeypatch.setattr(cli, "QOBUZ_DB", str(config_dir / "qobuz.db"))
    return str(config_file)


@pytest.fixture(autouse=True)
def _no_real_qobuzdl(monkeypatch):
    """Replace QobuzDL so tests don't touch the filesystem or network."""
    fake = MagicMock()
    fake_class = MagicMock(return_value=fake)
    monkeypatch.setattr(cli, "QobuzDL", fake_class)
    monkeypatch.setattr(cli, "_handle_commands", MagicMock())
    return fake


def test_main_dispatches_to_token_auth_when_present(tmp_path, monkeypatch, _no_real_qobuzdl):
    config_file = _patch_cli_paths(monkeypatch, tmp_path)
    _write_config(
        config_file,
        user_id="3394846",
        user_auth_token="real-token",
    )
    monkeypatch.setattr("sys.argv", ["qobuz-dl", "fun"])

    cli.main()

    _no_real_qobuzdl.initialize_client_with_token.assert_called_once()
    args, _kwargs = _no_real_qobuzdl.initialize_client_with_token.call_args
    assert args[0] == "3394846"
    assert args[1] == "real-token"
    assert args[2] == "798273057"


def test_main_no_config_file_runs_reset(tmp_path, monkeypatch):
    """Branch (b): no config file at all -> interactive reset."""
    config_dir = tmp_path / "qobuz-dl"
    config_file = config_dir / "config.ini"
    monkeypatch.setattr(cli, "CONFIG_PATH", str(config_dir))
    monkeypatch.setattr(cli, "CONFIG_FILE", str(config_file))
    monkeypatch.setattr(cli, "QOBUZ_DB", str(config_dir / "qobuz.db"))
    monkeypatch.setattr("sys.argv", ["qobuz-dl"])

    reset_calls = []

    def fake_reset(target):
        reset_calls.append(target)
        # Simulate an empty/uncreated config to terminate main early.
        raise SystemExit(0)

    monkeypatch.setattr(cli, "_reset_config", fake_reset)

    with pytest.raises(SystemExit):
        cli.main()
    assert reset_calls == [str(config_file)]


def test_main_legacy_email_password_exits_with_migration_message(
    tmp_path, monkeypatch, capsys
):
    """Branch (d): old config with email/password but no token -> exit(2)."""
    config_file = _patch_cli_paths(monkeypatch, tmp_path)
    _write_config(
        config_file,
        email="user@example.com",
        password="md5hash",
    )
    monkeypatch.setattr("sys.argv", ["qobuz-dl", "fun"])

    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2

    err = capsys.readouterr().err
    assert "no longer supported" in err.lower() or "deprecated" in err.lower()
    assert "--reset" in err or "user_id" in err


def test_main_corrupt_config_exits_with_pointer_to_reset(
    tmp_path, monkeypatch, capsys
):
    """Branch (e): config exists but configparser raises -> exit(2)."""
    config_file = _patch_cli_paths(monkeypatch, tmp_path)
    # Write an unparseable config file.
    with open(config_file, "w", encoding="utf-8") as f:
        f.write("[[[ not a valid ini file\n")
    monkeypatch.setattr("sys.argv", ["qobuz-dl", "fun"])

    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2

    err = capsys.readouterr().err
    assert "--reset" in err or "corrupt" in err.lower()


def test_main_semantically_corrupt_config_exits_cleanly(
    tmp_path, monkeypatch, capsys
):
    """Branch (e), part 2: config parses fine but a boolean value is junk
    (`no_cover = maybe`). configparser.getboolean raises ValueError.
    The CLI must exit(2) cleanly, not traceback.
    """
    config_file = _patch_cli_paths(monkeypatch, tmp_path)
    _write_config(
        config_file,
        user_id="3394846",
        user_auth_token="t",
        no_cover="maybe",  # not a valid bool
    )
    monkeypatch.setattr("sys.argv", ["qobuz-dl", "fun"])

    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2

    err = capsys.readouterr().err
    assert "--reset" in err or "corrupt" in err.lower()


def test_main_no_credentials_in_otherwise_valid_config_exits(
    tmp_path, monkeypatch, capsys
):
    """Branch (f): config parses but has no creds at all -> exit(2)."""
    config_file = _patch_cli_paths(monkeypatch, tmp_path)
    _write_config(config_file)  # no user_id/email/password
    monkeypatch.setattr("sys.argv", ["qobuz-dl", "fun"])

    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2

    err = capsys.readouterr().err
    assert "--reset" in err or "credentials" in err.lower()


def test_main_quality_fallback_wiring(tmp_path, monkeypatch, _no_real_qobuzdl):
    """Pin the no_fallback boolean wiring: setting `no_fallback=true` in
    the config (or `--no-fallback` on the CLI) MUST disable quality
    fallback. Regression test for cli.py:268 — the original
    `not arguments.no_fallback or not no_fallback` was
    `(not A) or (not B)` and only honored the flag when both sources
    agreed.
    """
    config_file = _patch_cli_paths(monkeypatch, tmp_path)

    # Case 1: config-only no_fallback=true, no CLI flag → fallback disabled.
    _write_config(
        config_file,
        user_id="3394846",
        user_auth_token="real-token",
        no_fallback="true",
    )
    monkeypatch.setattr("sys.argv", ["qobuz-dl", "fun"])
    cli.main()
    _, kwargs = cli.QobuzDL.call_args
    assert kwargs["quality_fallback"] is False, (
        "config no_fallback=true should disable quality_fallback "
        "(regression — boolean wiring bug)"
    )

    # Case 2: config no_fallback=false, CLI --no-fallback → fallback disabled.
    _write_config(
        config_file,
        user_id="3394846",
        user_auth_token="real-token",
        no_fallback="false",
    )
    cli.QobuzDL.reset_mock()
    monkeypatch.setattr("sys.argv", ["qobuz-dl", "fun", "--no-fallback"])
    cli.main()
    _, kwargs = cli.QobuzDL.call_args
    assert kwargs["quality_fallback"] is False

    # Case 3: both false → fallback enabled.
    _write_config(
        config_file,
        user_id="3394846",
        user_auth_token="real-token",
        no_fallback="false",
    )
    cli.QobuzDL.reset_mock()
    monkeypatch.setattr("sys.argv", ["qobuz-dl", "fun"])
    cli.main()
    _, kwargs = cli.QobuzDL.call_args
    assert kwargs["quality_fallback"] is True


def test_main_corrupt_config_does_not_echo_token(tmp_path, monkeypatch, capsys):
    """Pin the contract: when the config is malformed in a way that
    triggers configparser.ParsingError, the error message printed to
    stderr MUST NOT include the offending source line (which can be the
    `user_auth_token = ...` line itself).
    """
    config_file = _patch_cli_paths(monkeypatch, tmp_path)
    SECRET = "ABC-VERY-SECRET-TOKEN-IN-BAD-LINE"
    # Hand-rolled malformed INI: a continuation line with no preceding key.
    with open(config_file, "w", encoding="utf-8") as f:
        f.write(
            "[DEFAULT]\n"
            "  bogus continuation line\n"
            f"user_auth_token = {SECRET}\n"
        )
    monkeypatch.setattr("sys.argv", ["qobuz-dl", "fun"])

    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2

    err = capsys.readouterr().err
    assert SECRET not in err, (
        "stderr leaked the user_auth_token via raw configparser error message"
    )
    # Should still be informative.
    assert "--reset" in err


def test_main_unicode_decode_error_in_config(tmp_path, monkeypatch, capsys):
    """Non-UTF-8 bytes in the config file (e.g. cp1252-encoded by a
    Windows editor) must surface as a clean exit(2), not a traceback.
    Cross-platform test: writes raw bytes, doesn't depend on filesystem
    encoding semantics.
    """
    config_file = _patch_cli_paths(monkeypatch, tmp_path)
    # 0xff is invalid as a UTF-8 leading byte.
    with open(config_file, "wb") as f:
        f.write(b"[DEFAULT]\nuser_id = \xff\xfe\n")
    monkeypatch.setattr("sys.argv", ["qobuz-dl", "fun"])

    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "--reset" in err or "corrupt" in err.lower()


def test_main_stale_token_exits_cleanly_not_traceback(
    tmp_path, monkeypatch, capsys, _no_real_qobuzdl
):
    """A revoked / stale `user_auth_token` causes Client.from_token to
    raise AuthenticationError. main() must exit(2) with the message,
    not propagate a traceback.
    """
    from qobuz_dl.exceptions import AuthenticationError

    config_file = _patch_cli_paths(monkeypatch, tmp_path)
    _write_config(
        config_file,
        user_id="3394846",
        user_auth_token="stale-token",
    )
    _no_real_qobuzdl.initialize_client_with_token.side_effect = AuthenticationError(
        "Invalid token credentials.\nReset your credentials with 'qobuz-dl -r'"
    )
    monkeypatch.setattr("sys.argv", ["qobuz-dl", "fun"])

    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "Invalid token credentials" in err
    assert "qobuz-dl -r" in err


def test_main_show_config_works_when_config_corrupt(tmp_path, monkeypatch, capsys):
    """`--show-config` must work even when the strict config-load would
    fail — that's the case where users most need to inspect the file.
    Regression for the M2 reordering.
    """
    config_file = _patch_cli_paths(monkeypatch, tmp_path)
    # Malformed INI but contains a (redactable) user_auth_token.
    with open(config_file, "w", encoding="utf-8") as f:
        f.write(
            "[DEFAULT]\n"
            "  bad continuation line\n"
            "user_auth_token = SECRET-IN-CORRUPT-CONFIG\n"
        )
    monkeypatch.setattr("sys.argv", ["qobuz-dl", "--show-config"])

    with pytest.raises(SystemExit) as exc:
        cli.main()
    # show_config exits with sys.exit() → code is None.
    assert exc.value.code in (None, 0)

    out = capsys.readouterr().out
    # The fallback regex in _redact_config_text handles malformed INI.
    assert "SECRET-IN-CORRUPT-CONFIG" not in out
    assert "***REDACTED***" in out


def test_main_purge_works_when_config_corrupt(tmp_path, monkeypatch, capsys):
    """`--purge` must not be gated behind a successful config-load."""
    config_file = _patch_cli_paths(monkeypatch, tmp_path)
    # Truly broken config.
    with open(config_file, "w", encoding="utf-8") as f:
        f.write("[[[ totally broken\n")
    # Create a fake DB file so we can prove --purge removed it.
    db_file = tmp_path / "qobuz-dl" / "qobuz.db"
    db_file.write_text("fake")
    monkeypatch.setattr("sys.argv", ["qobuz-dl", "--purge"])

    with pytest.raises(SystemExit):
        cli.main()
    assert not db_file.exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["qobuz-dl", "dl", "https://example/album/x"],
        ["qobuz-dl", "fun"],
        ["qobuz-dl", "lucky", "some", "query"],
    ],
)
def test_main_download_subcommand_with_no_secret_warns_and_exits(
    tmp_path, monkeypatch, capsys, _no_real_qobuzdl, argv
):
    """If login succeeds but cfg_setup couldn't validate any secret
    (i.e. client.sec is None), every download-capable subcommand must
    exit cleanly with code 3 + README pointer rather than tracebacking
    from InvalidAppSecretError mid-download.
    """
    config_file = _patch_cli_paths(monkeypatch, tmp_path)
    _write_config(
        config_file,
        user_id="3394846",
        user_auth_token="real-token",
    )
    _no_real_qobuzdl.client = MagicMock()
    _no_real_qobuzdl.client.sec = None
    monkeypatch.setattr("sys.argv", argv)

    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 3

    err = capsys.readouterr().err
    assert "downloads currently fail" in err.lower() or "signing" in err.lower()
    assert "readme" in err.lower() or "see " in err.lower()
