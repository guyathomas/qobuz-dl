# Wrapper for Qo-DL Reborn. This is a sligthly modified version
# of qopy, originally written by Sorrow446. All credits to the
# original author.

import hashlib
import logging
import time

import requests

from qobuz_dl.exceptions import (
    AuthenticationError,
    IneligibleError,
    InvalidAppIdError,
    InvalidAppSecretError,
    InvalidQuality,
)
from qobuz_dl.color import GREEN, YELLOW

RESET = "Reset your credentials with 'qobuz-dl -r'"

logger = logging.getLogger(__name__)


_DOWNLOAD_BROKEN_WARNING = (
    "Could not validate any app secret. Qobuz changed their request-signing "
    "scheme in April 2026 and downloads will fail until that's reimplemented. "
    "Login and metadata/search still work. See the README for details."
)

# Network timeouts: (connect_seconds, read_seconds). All session.get/post
# calls in this module pass this so a stalled Qobuz endpoint can never
# hang the CLI indefinitely.
_REQUEST_TIMEOUT = (5, 30)


def _extract_label(usr_info):
    """Best-effort membership label extraction.

    Order: credential.parameters.short_label, credential.parameters.label,
    credential.label. Falls back to "Unknown" rather than KeyError so a
    minor response-shape change doesn't break login.
    """
    credential = usr_info.get("user", {}).get("credential", {}) or {}
    params = credential.get("parameters") or {}
    return (
        params.get("short_label")
        or params.get("label")
        or credential.get("label")
        or "Unknown"
    )


class Client:
    def __init__(self, app_id, secrets):
        # Email/password login was disabled server-side in April 2026.
        # The constructor only sets up state; callers MUST authenticate via
        # `Client.from_token(...)`.
        self.secrets = secrets
        self.id = str(app_id)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:83.0) Gecko/20100101 Firefox/83.0",
                "X-App-Id": self.id,
                "Content-Type": "application/json;charset=UTF-8",
            }
        )
        self.base = "https://www.qobuz.com/api.json/0.2/"
        self.sec = None
        self.uat = None
        self.label = None

    @classmethod
    def from_token(cls, user_id, user_auth_token, app_id, secrets):
        """Authenticate via Qobuz's token-login endpoint and return a
        ready-to-use Client. Raises:
          - AuthenticationError on 401 or unexpected response shape
          - InvalidAppIdError on 400
          - IneligibleError when the account has no streaming entitlements

        cfg_setup() failure is downgraded to a logged warning. Both the
        narrow `InvalidAppSecretError` (every secret rejected by the new
        signing scheme) and broader transport-level errors during the
        secret probe are tolerated so login + metadata/search keep working
        even when the download endpoint is misbehaving.
        """
        client = cls(app_id, secrets)
        client._authenticate_with_token(user_id, user_auth_token)
        try:
            client.cfg_setup()
        except (InvalidAppSecretError, requests.RequestException, ValueError):
            logger.warning(f"{YELLOW}{_DOWNLOAD_BROKEN_WARNING}")
        return client

    def _authenticate_with_token(self, user_id, user_auth_token):
        logger.info(f"{YELLOW}Logging in...")
        params = {
            "user_id": str(user_id),
            "user_auth_token": user_auth_token,
            "app_id": self.id,
        }
        try:
            r = self.session.get(
                self.base + "user/login",
                params=params,
                timeout=_REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            # Strip URL-bearing details: the token is in the query string
            # and exc.request.url contains it verbatim.
            raise AuthenticationError(
                f"Could not reach Qobuz login endpoint: "
                f"{type(exc).__name__}.\n" + RESET
            ) from None

        if r.status_code == 401:
            raise AuthenticationError("Invalid token credentials.\n" + RESET)
        if r.status_code == 400:
            raise InvalidAppIdError("Invalid app id.\n" + RESET)
        if not r.ok:
            # Don't call r.raise_for_status(): the resulting HTTPError's
            # str() embeds request.url, which contains user_auth_token.
            raise AuthenticationError(
                f"Login failed: HTTP {r.status_code}.\n" + RESET
            )

        try:
            usr_info = r.json()
        except ValueError:
            raise AuthenticationError(
                "Unexpected non-JSON login response from Qobuz.\n" + RESET
            ) from None

        if not usr_info.get("user", {}).get("credential", {}).get("parameters"):
            raise IneligibleError(
                "Free accounts are not eligible to download tracks."
            )

        # Trust the user-supplied token rather than relying on the response
        # to echo it back — the /user/login response shape is not contractual.
        self.uat = user_auth_token
        self.session.headers.update({"X-User-Auth-Token": self.uat})
        self.label = _extract_label(usr_info)
        logger.info(f"{GREEN}Membership: {self.label}")

    def api_call(self, epoint, **kwargs):
        if epoint == "track/get":
            params = {"track_id": kwargs["id"]}
        elif epoint == "album/get":
            params = {"album_id": kwargs["id"]}
        elif epoint == "playlist/get":
            params = {
                "extra": "tracks",
                "playlist_id": kwargs["id"],
                "limit": 500,
                "offset": kwargs["offset"],
            }
        elif epoint == "artist/get":
            params = {
                "app_id": self.id,
                "artist_id": kwargs["id"],
                "limit": 500,
                "offset": kwargs["offset"],
                "extra": "albums",
            }
        elif epoint == "label/get":
            params = {
                "label_id": kwargs["id"],
                "limit": 500,
                "offset": kwargs["offset"],
                "extra": "albums",
            }
        elif epoint == "favorite/getUserFavorites":
            unix = time.time()
            # r_sig = "userLibrarygetAlbumsList" + str(unix) + kwargs["sec"]
            r_sig = "favoritegetUserFavorites" + str(unix) + kwargs["sec"]
            r_sig_hashed = hashlib.md5(r_sig.encode("utf-8")).hexdigest()
            params = {
                "app_id": self.id,
                "user_auth_token": self.uat,
                "type": "albums",
                "request_ts": unix,
                "request_sig": r_sig_hashed,
            }
        elif epoint == "track/getFileUrl":
            unix = time.time()
            track_id = kwargs["id"]
            fmt_id = kwargs["fmt_id"]
            if int(fmt_id) not in (5, 6, 7, 27):
                raise InvalidQuality("Invalid quality id: choose between 5, 6, 7 or 27")
            r_sig = "trackgetFileUrlformat_id{}intentstreamtrack_id{}{}{}".format(
                fmt_id, track_id, unix, kwargs.get("sec", self.sec)
            )
            r_sig_hashed = hashlib.md5(r_sig.encode("utf-8")).hexdigest()
            params = {
                "request_ts": unix,
                "request_sig": r_sig_hashed,
                "track_id": track_id,
                "format_id": fmt_id,
                "intent": "stream",
            }
        else:
            params = kwargs
        r = self.session.get(self.base + epoint, params=params, timeout=_REQUEST_TIMEOUT)
        if (
            epoint in ["track/getFileUrl", "favorite/getUserFavorites"]
            and r.status_code == 400
        ):
            # Embed only the server's `message` field; the full body is
            # uncontracted and could echo request params (token-bearing).
            try:
                msg = r.json().get("message", "")
            except ValueError:
                msg = ""
            raise InvalidAppSecretError(f"Invalid app secret ({msg}).\n" + RESET)

        if not r.ok:
            # Don't call r.raise_for_status(): some endpoints
            # (favorite/getUserFavorites) embed user_auth_token in the query
            # string, and HTTPError's str()/repr() echoes request.url verbatim.
            # Raise a sanitized HTTPError that drops the URL.
            raise requests.HTTPError(
                f"HTTP {r.status_code} from {epoint}"
            ) from None
        return r.json()

    def multi_meta(self, epoint, key, id, type):
        total = 1
        offset = 0
        while total > 0:
            if type in ["tracks", "albums"]:
                j = self.api_call(epoint, id=id, offset=offset, type=type)[type]
            else:
                j = self.api_call(epoint, id=id, offset=offset, type=type)
            if offset == 0:
                yield j
                total = j[key] - 500
            else:
                yield j
                total -= 500
            offset += 500

    def get_album_meta(self, id):
        return self.api_call("album/get", id=id)

    def get_track_meta(self, id):
        return self.api_call("track/get", id=id)

    def get_track_url(self, id, fmt_id):
        return self.api_call("track/getFileUrl", id=id, fmt_id=fmt_id)

    def get_artist_meta(self, id):
        return self.multi_meta("artist/get", "albums_count", id, None)

    def get_plist_meta(self, id):
        return self.multi_meta("playlist/get", "tracks_count", id, None)

    def get_label_meta(self, id):
        return self.multi_meta("label/get", "albums_count", id, None)

    def search_albums(self, query, limit):
        return self.api_call("album/search", query=query, limit=limit)

    def search_artists(self, query, limit):
        return self.api_call("artist/search", query=query, limit=limit)

    def search_playlists(self, query, limit):
        return self.api_call("playlist/search", query=query, limit=limit)

    def search_tracks(self, query, limit):
        return self.api_call("track/search", query=query, limit=limit)

    def get_favorite_albums(self, offset, limit):
        return self.api_call(
            "favorite/getUserFavorites", type="albums", offset=offset, limit=limit
        )

    def get_favorite_tracks(self, offset, limit):
        return self.api_call(
            "favorite/getUserFavorites", type="tracks", offset=offset, limit=limit
        )

    def get_favorite_artists(self, offset, limit):
        return self.api_call(
            "favorite/getUserFavorites", type="artists", offset=offset, limit=limit
        )

    def get_user_playlists(self, limit):
        return self.api_call("playlist/getUserPlaylists", limit=limit)

    def test_secret(self, sec):
        try:
            self.api_call("track/getFileUrl", id=5966783, fmt_id=5, sec=sec)
            return True
        except InvalidAppSecretError:
            return False

    def cfg_setup(self):
        for secret in self.secrets:
            # Falsy secrets
            if not secret:
                continue

            if self.test_secret(secret):
                self.sec = secret
                break

        if self.sec is None:
            raise InvalidAppSecretError("Can't find any valid app secret.\n" + RESET)
