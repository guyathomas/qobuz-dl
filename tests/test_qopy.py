"""Tests for `qobuz_dl.qopy.Client`.

The old `Client(email, pwd, app_id, secrets)` constructor authenticated
inside __init__ via Qobuz's email/password flow, which Qobuz disabled
server-side in April 2026. The new constructor takes only (app_id, secrets)
and auth happens via `Client.from_token(...)`.
"""

import json
import logging
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from qobuz_dl.exceptions import (
    AuthenticationError,
    IneligibleError,
    InvalidAppIdError,
)
from qobuz_dl.qopy import Client

FIXTURES = Path(__file__).parent / "fixtures"
LOGIN_URL = "https://www.qobuz.com/api.json/0.2/user/login"
GETFILEURL_URL = "https://www.qobuz.com/api.json/0.2/track/getFileUrl"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# constructor surface
# ---------------------------------------------------------------------------


def test_old_init_signature_removed():
    """The legacy `Client(email, pwd, app_id, secrets)` signature must be
    gone. Calling it with that arity should raise TypeError so old callers
    fail loudly instead of silently constructing a broken client.
    """
    with pytest.raises(TypeError):
        Client("a@b.com", "pwd", "1", [])


# ---------------------------------------------------------------------------
# Client.from_token
# ---------------------------------------------------------------------------


@responses.activate
def test_from_token_happy_path():
    """A successful token login sets uat, the X-User-Auth-Token header,
    and a non-empty membership label.
    """
    responses.add(
        responses.GET,
        LOGIN_URL,
        json=_load_fixture("user_login_response_studio.json"),
        status=200,
    )
    # cfg_setup will probe track/getFileUrl. Make those probes fail so we
    # don't conflate the happy-path login test with cfg_setup behaviour
    # (covered separately).
    responses.add(
        responses.GET,
        GETFILEURL_URL,
        json={"code": 400, "message": "Invalid Request Signature parameter"},
        status=400,
    )

    client = Client.from_token(
        user_id="3394846",
        user_auth_token="real-token-xyz",
        app_id="798273057",
        secrets=["secret1"],
    )

    assert client.uat == "real-token-xyz"
    assert client.session.headers.get("X-User-Auth-Token") == "real-token-xyz"
    assert client.label  # non-empty
    assert client.label != "Unknown"


@responses.activate
def test_from_token_sends_correct_query_params():
    """The login request must carry user_id, user_auth_token, and app_id
    as GET query params (not headers, not body).
    """
    responses.add(
        responses.GET,
        LOGIN_URL,
        json=_load_fixture("user_login_response_studio.json"),
        status=200,
    )
    responses.add(responses.GET, GETFILEURL_URL, json={}, status=400)

    Client.from_token(
        user_id="3394846",
        user_auth_token="real-token-xyz",
        app_id="798273057",
        secrets=["secret1"],
    )

    login_call = next(c for c in responses.calls if "user/login" in c.request.url)
    qs = parse_qs(urlparse(login_call.request.url).query)
    assert qs["user_id"] == ["3394846"]
    assert qs["user_auth_token"] == ["real-token-xyz"]
    assert qs["app_id"] == ["798273057"]


@responses.activate
@pytest.mark.parametrize(
    "fixture,expected_label_contains",
    [
        ("user_login_response_studio.json", "Studio"),  # has short_label
        ("user_login_response_no_short_label.json", "Sublime"),  # parameters.label only
        ("user_login_response_credential_label_only.json", "Hi-Fi"),  # credential.label only
    ],
)
def test_from_token_label_extraction_tolerant(fixture, expected_label_contains):
    """Label is read from credential.parameters.short_label if present,
    else credential.parameters.label, else credential.label. None of
    these should raise KeyError if the response shape drifts.
    """
    responses.add(responses.GET, LOGIN_URL, json=_load_fixture(fixture), status=200)
    responses.add(responses.GET, GETFILEURL_URL, json={}, status=400)

    client = Client.from_token(
        user_id="3394846",
        user_auth_token="t",
        app_id="798273057",
        secrets=["s"],
    )
    assert expected_label_contains in client.label


@responses.activate
def test_from_token_label_extraction_falls_back_to_unknown():
    """If the response carries no recognizable label field, _extract_label
    must return "Unknown" instead of raising KeyError. This protects
    against minor schema drift on Qobuz's side.
    """
    responses.add(
        responses.GET,
        LOGIN_URL,
        json={
            "user_auth_token": "FAKE",
            "user": {
                "id": 1,
                "credential": {
                    "id": 1,
                    # no `label` here, no `parameters` either ...
                    "parameters": {"lossy_streaming": True},
                },
            },
        },
        status=200,
    )
    responses.add(responses.GET, GETFILEURL_URL, json={}, status=400)

    client = Client.from_token(
        user_id="1",
        user_auth_token="t",
        app_id="798273057",
        secrets=["s"],
    )
    assert client.label == "Unknown"


@responses.activate
def test_from_token_401_raises_auth_error():
    responses.add(
        responses.GET,
        LOGIN_URL,
        json={"code": 401, "message": "User authentication is required."},
        status=401,
    )
    with pytest.raises(AuthenticationError):
        Client.from_token(
            user_id="3394846",
            user_auth_token="bad-token",
            app_id="798273057",
            secrets=["s"],
        )


@responses.activate
def test_from_token_400_raises_invalid_app_id():
    responses.add(
        responses.GET,
        LOGIN_URL,
        json={"code": 400, "message": "Invalid app id."},
        status=400,
    )
    with pytest.raises(InvalidAppIdError):
        Client.from_token(
            user_id="3394846",
            user_auth_token="t",
            app_id="badappid",
            secrets=["s"],
        )


@responses.activate
def test_from_token_free_account_raises_ineligible():
    responses.add(
        responses.GET,
        LOGIN_URL,
        json=_load_fixture("user_login_response_free.json"),
        status=200,
    )
    with pytest.raises(IneligibleError):
        Client.from_token(
            user_id="3394846",
            user_auth_token="t",
            app_id="798273057",
            secrets=["s"],
        )


@responses.activate
def test_from_token_does_not_leak_token_on_5xx(caplog):
    """A non-401/400 server error must NOT propagate the request URL
    (which contains user_auth_token) into the exception text or logs.
    """
    SECRET = "TOTALLY-SECRET-TOKEN-DO-NOT-LEAK"
    responses.add(
        responses.GET,
        LOGIN_URL,
        json={"code": 503, "message": "Service Unavailable"},
        status=503,
    )

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(AuthenticationError) as exc_info:
            Client.from_token(
                user_id="3394846",
                user_auth_token=SECRET,
                app_id="798273057",
                secrets=["s"],
            )

    assert SECRET not in str(exc_info.value)
    assert SECRET not in repr(exc_info.value)
    assert SECRET not in caplog.text


@responses.activate
def test_from_token_does_not_leak_token_on_connection_error(caplog):
    """A network error must NOT surface the URL or token via the
    propagated exception message.
    """
    SECRET = "TOTALLY-SECRET-TOKEN-DO-NOT-LEAK"
    # Deliberately don't register a mock; responses raises ConnectionError.

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(AuthenticationError) as exc_info:
            Client.from_token(
                user_id="3394846",
                user_auth_token=SECRET,
                app_id="798273057",
                secrets=["s"],
            )

    assert SECRET not in str(exc_info.value)
    assert SECRET not in repr(exc_info.value)
    assert SECRET not in caplog.text


@responses.activate
def test_from_token_handles_non_json_login_response():
    """A 200 with an HTML body (proxy interstitial, captcha) must surface
    as AuthenticationError, not a JSONDecodeError traceback.
    """
    responses.add(
        responses.GET,
        LOGIN_URL,
        body="<html>Service unavailable</html>",
        status=200,
        content_type="text/html",
    )
    with pytest.raises(AuthenticationError):
        Client.from_token(
            user_id="3394846",
            user_auth_token="t",
            app_id="798273057",
            secrets=["s"],
        )


@responses.activate
def test_from_token_succeeds_when_cfg_setup_fails(caplog):
    """If cfg_setup() can't validate any secret (the 2026 SHA-256 signing
    migration breaks the MD5-signed track/getFileUrl probe), login itself
    must still succeed and the client must still be usable for
    metadata/search. `client.sec` stays None and a clear warning is
    emitted so users know downloads will fail.
    """
    responses.add(
        responses.GET,
        LOGIN_URL,
        json=_load_fixture("user_login_response_studio.json"),
        status=200,
    )
    # Every secret probe returns 400.
    responses.add(
        responses.GET,
        GETFILEURL_URL,
        json={"code": 400, "message": "Invalid Request Signature parameter"},
        status=400,
    )

    with caplog.at_level(logging.WARNING):
        client = Client.from_token(
            user_id="3394846",
            user_auth_token="t",
            app_id="798273057",
            secrets=["secretA", "secretB", "secretC"],
        )

    assert client.uat == "t"
    assert client.sec is None
    assert any(
        "downloads will fail" in record.message.lower()
        or "signing" in record.message.lower()
        for record in caplog.records
    ), f"expected a download-broken warning in logs; got: {[r.message for r in caplog.records]}"


@responses.activate
def test_api_call_does_not_leak_token_on_http_error(caplog):
    """`api_call('favorite/getUserFavorites', ...)` includes user_auth_token
    in the GET query string. Any non-2xx (other than 400) used to call
    `r.raise_for_status()`, whose HTTPError str/repr embeds request.url
    verbatim — leaking the token to logs and tracebacks. Pin the contract:
    the sanitized HTTPError must not echo the URL.
    """
    import requests
    from qobuz_dl.qopy import Client

    SECRET_UAT = "API-CALL-LEAK-CANARY-TOKEN"
    FAVORITES_URL = "https://www.qobuz.com/api.json/0.2/favorite/getUserFavorites"

    # Login OK to populate self.uat = SECRET_UAT.
    responses.add(
        responses.GET,
        LOGIN_URL,
        json=_load_fixture("user_login_response_studio.json"),
        status=200,
    )
    # cfg_setup probes always fail (degraded mode) — keeps the test
    # focused on api_call, not cfg_setup.
    responses.add(
        responses.GET,
        GETFILEURL_URL,
        json={"code": 400, "message": "fail"},
        status=400,
    )
    # favorite/getUserFavorites returns a 503.
    responses.add(
        responses.GET,
        FAVORITES_URL,
        json={"code": 503, "message": "Service Unavailable"},
        status=503,
    )

    client = Client.from_token(
        user_id="3394846",
        user_auth_token=SECRET_UAT,
        app_id="798273057",
        secrets=["s"],
    )

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(requests.HTTPError) as exc_info:
            # Call api_call directly with the signature secret —
            # mirrors what download paths do once the new SHA-256 signing
            # is reimplemented. user_auth_token still ends up in the
            # query string regardless of `sec` value.
            client.api_call(
                "favorite/getUserFavorites",
                type="albums",
                offset=0,
                limit=10,
                sec="fake-secret",
            )

    assert SECRET_UAT not in str(exc_info.value)
    assert SECRET_UAT not in repr(exc_info.value)
    assert SECRET_UAT not in caplog.text
    # Belt-and-braces: also no leaked URL via the chained context.
    assert SECRET_UAT not in repr(exc_info.value.__context__)


@responses.activate
def test_from_token_succeeds_when_cfg_setup_hits_transport_error(caplog):
    """cfg_setup probes are HTTP calls — if one of them raises a transient
    ConnectionError (or 5xx) the codex-flagged downgrade must catch
    requests.RequestException, not just InvalidAppSecretError. Login
    itself already succeeded; the secret list just couldn't be probed.
    """
    responses.add(
        responses.GET,
        LOGIN_URL,
        json=_load_fixture("user_login_response_studio.json"),
        status=200,
    )
    # No mock for getFileUrl → responses raises ConnectionError.

    with caplog.at_level(logging.WARNING):
        client = Client.from_token(
            user_id="3394846",
            user_auth_token="t",
            app_id="798273057",
            secrets=["secretA"],
        )

    assert client.uat == "t"
    assert client.sec is None  # cfg_setup couldn't validate any secret
    assert any(
        "downloads will fail" in r.message.lower()
        for r in caplog.records
    )
