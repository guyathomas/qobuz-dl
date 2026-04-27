"""Canary tests against a captured live `bundle.js` excerpt.

If Qobuz changes their bundle format these tests fail loudly, instead of
the change being detected only when a real user runs `qobuz-dl -r`.
"""

from qobuz_dl.bundle import _APP_ID_REGEX


def test_app_id_regex_matches_fixture(bundle_snippet):
    match = _APP_ID_REGEX.search(bundle_snippet)
    assert match is not None, "_APP_ID_REGEX no longer matches the live bundle"
    assert match.group("app_id") == "798273057"


def test_localuser_marker_present_in_fixture(bundle_snippet):
    """The Qobuz web player stores its auth blob under
    `localStorage.localuser`. This test pins the storage key so the
    token-capture instructions in the README/UX stay correct.
    """
    assert "localuser" in bundle_snippet, (
        "The 'localuser' marker is missing from the bundle. "
        "Qobuz may have renamed the localStorage key — update the "
        "token-capture UX in `_reset_config` and the README."
    )
