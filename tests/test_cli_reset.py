"""Tests for `qobuz_dl.cli._reset_config`.

The reset flow now prompts only for `user_id` + `user_auth_token`
(email/password is gone). It must use the atomic config-write helper
and never persist a `password` or `email` key.
"""

import configparser
from collections import OrderedDict
from unittest.mock import MagicMock, patch

import pytest

from qobuz_dl import cli


@pytest.fixture
def fake_bundle(monkeypatch):
    """Stub `qobuz_dl.cli.Bundle()` so reset doesn't hit play.qobuz.com."""
    bundle = MagicMock()
    bundle.get_app_id.return_value = "798273057"
    bundle.get_secrets.return_value = OrderedDict([("london", "secretA"), ("paris", "secretB")])
    monkeypatch.setattr(cli, "Bundle", lambda: bundle)
    return bundle


def test_reset_writes_token_keys_only(tmp_path, fake_bundle):
    target = tmp_path / "config.ini"
    # user_id + folder + quality go through input(); user_auth_token uses
    # getpass so the token is never echoed to terminal scrollback.
    plain_inputs = iter(["3394846", "", ""])
    with patch("builtins.input", lambda *_a, **_kw: next(plain_inputs)), \
         patch("qobuz_dl.cli.getpass.getpass", return_value="real-token-xyz"):
        cli._reset_config(str(target))

    parser = configparser.ConfigParser()
    parser.read(str(target))

    assert parser["DEFAULT"]["user_id"] == "3394846"
    assert parser["DEFAULT"]["user_auth_token"] == "real-token-xyz"
    assert parser["DEFAULT"]["app_id"] == "798273057"
    assert "secretA" in parser["DEFAULT"]["secrets"]

    # Email/password must NOT be written by the new reset flow.
    assert "email" not in parser["DEFAULT"]
    assert "password" not in parser["DEFAULT"]


def test_reset_uses_getpass_for_token(tmp_path, fake_bundle):
    """Pin the contract: user_auth_token must NOT be collected via plain
    input() (which echoes to terminal scrollback / tmux / screen-share).
    Regression guard for the M5 fix.
    """
    target = tmp_path / "config.ini"
    plain_inputs = iter(["3394846", "", ""])
    with patch("builtins.input", lambda *_a, **_kw: next(plain_inputs)) as input_mock, \
         patch("qobuz_dl.cli.getpass.getpass") as getpass_mock:
        getpass_mock.return_value = "secret-token"
        cli._reset_config(str(target))

    # getpass.getpass MUST have been the prompt that received the token.
    getpass_mock.assert_called_once()
    parser = configparser.ConfigParser()
    parser.read(str(target))
    assert parser["DEFAULT"]["user_auth_token"] == "secret-token"


def test_reset_uses_atomic_writer(tmp_path, fake_bundle, monkeypatch):
    """Pin the contract: `_reset_config` must funnel through
    `atomic_write_config`, never `open(..., 'w')` directly. A regression
    here would risk partial writes to the credentials store.
    """
    target = tmp_path / "config.ini"
    seen = {}

    def fake_atomic(path, parser):
        seen["path"] = path
        seen["user_id"] = parser["DEFAULT"]["user_id"]
        seen["user_auth_token"] = parser["DEFAULT"]["user_auth_token"]
        # Don't actually write — proves the test holds even when the writer is mocked.

    monkeypatch.setattr(cli, "atomic_write_config", fake_atomic)
    plain_inputs = iter(["3394846", "", ""])
    with patch("builtins.input", lambda *_a, **_kw: next(plain_inputs)), \
         patch("qobuz_dl.cli.getpass.getpass", return_value="t"):
        cli._reset_config(str(target))

    assert seen == {
        "path": str(target),
        "user_id": "3394846",
        "user_auth_token": "t",
    }
    # Confirm: nothing was written through any other path.
    assert not target.exists()
