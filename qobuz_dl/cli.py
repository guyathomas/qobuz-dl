import configparser
import getpass
import io
import logging
import glob
import os
import re
import sys

from qobuz_dl._config_io import atomic_write_config
from qobuz_dl.bundle import Bundle
from qobuz_dl.color import GREEN, RED, YELLOW
from qobuz_dl.commands import qobuz_dl_args
from qobuz_dl.core import QobuzDL
from qobuz_dl.downloader import DEFAULT_FOLDER, DEFAULT_TRACK
from qobuz_dl.exceptions import (
    AuthenticationError,
    IneligibleError,
    InvalidAppIdError,
    InvalidAppSecretError,
)

logger = logging.getLogger(__name__)

TOKEN_CAPTURE_INSTRUCTIONS = """\
To get your user_id and user_auth_token:
  1. Open https://play.qobuz.com in your browser and log in.
  2. Open DevTools (F12) -> Console tab.
  3. Paste this and press Enter:
         JSON.parse(localStorage.getItem('localuser'))
  4. Copy the `id` and `user_auth_token` fields from the result.

Fallback (if console is disabled): DevTools -> Application tab ->
Local Storage -> https://play.qobuz.com -> click the `localuser` row.
The value is a JSON blob with the same `id` and `user_auth_token` fields.
"""

if os.name == "nt":
    OS_CONFIG = os.environ.get("APPDATA")
else:
    OS_CONFIG = os.path.join(os.environ["HOME"], ".config")

CONFIG_PATH = os.path.join(OS_CONFIG, "qobuz-dl")
CONFIG_FILE = os.path.join(CONFIG_PATH, "config.ini")
QOBUZ_DB = os.path.join(CONFIG_PATH, "qobuz_dl.db")


def _reset_config(config_file):
    logger.info(f"{YELLOW}Creating config file: {config_file}")
    print(TOKEN_CAPTURE_INSTRUCTIONS)
    user_id = input("user_id: ").strip()
    # getpass keeps the token out of terminal scrollback / tmux buffers /
    # screen-share. Cross-platform: termios on POSIX, msvcrt on Windows.
    user_auth_token = getpass.getpass("user_auth_token (input hidden): ").strip()

    default_folder = (
        input("Folder for downloads (leave empty for default 'Qobuz Downloads'): ")
        or "Qobuz Downloads"
    )
    default_quality = (
        input(
            "Download quality (5, 6, 7, 27) "
            "[320, LOSSLESS, 24B <96KHZ, 24B >96KHZ] (leave empty for default '6'): "
        )
        or "6"
    )

    config = configparser.ConfigParser()
    config["DEFAULT"]["user_id"] = user_id
    config["DEFAULT"]["user_auth_token"] = user_auth_token
    config["DEFAULT"]["default_folder"] = default_folder
    config["DEFAULT"]["default_quality"] = default_quality
    config["DEFAULT"]["default_limit"] = "20"
    config["DEFAULT"]["no_m3u"] = "false"
    config["DEFAULT"]["albums_only"] = "false"
    config["DEFAULT"]["no_fallback"] = "false"
    config["DEFAULT"]["og_cover"] = "false"
    config["DEFAULT"]["embed_art"] = "false"
    config["DEFAULT"]["no_cover"] = "false"
    config["DEFAULT"]["no_database"] = "false"

    logger.info(f"{YELLOW}Fetching app_id and secrets from play.qobuz.com bundle...")
    bundle = Bundle()
    config["DEFAULT"]["app_id"] = str(bundle.get_app_id())
    config["DEFAULT"]["secrets"] = ",".join(bundle.get_secrets().values())
    config["DEFAULT"]["folder_format"] = DEFAULT_FOLDER
    config["DEFAULT"]["track_format"] = DEFAULT_TRACK
    config["DEFAULT"]["smart_discography"] = "false"

    atomic_write_config(config_file, config)
    logger.info(
        f"{GREEN}Config file updated. Edit more options in {config_file}"
        "\nso you don't have to call custom flags every time you run "
        "a qobuz-dl command."
    )


def _remove_leftovers(directory):
    directory = os.path.join(directory, "**", ".*.tmp")
    for i in glob.glob(directory, recursive=True):
        try:
            os.remove(i)
        except:  # noqa
            pass


def _handle_commands(qobuz, arguments):
    try:
        if arguments.command == "dl":
            qobuz.download_list_of_urls(arguments.SOURCE)
        elif arguments.command == "lucky":
            query = " ".join(arguments.QUERY)
            qobuz.lucky_type = arguments.type
            qobuz.lucky_limit = arguments.number
            qobuz.lucky_mode(query)
        else:
            qobuz.interactive_limit = arguments.limit
            qobuz.interactive()

    except InvalidAppSecretError:
        # Belt-and-braces: the pre-flight `client.sec is None` guard in
        # main() catches the common case, but if Qobuz only rejects a
        # secret mid-download (e.g. partial server-side rollout), this
        # ensures the user sees a clean exit instead of a traceback.
        sys.stderr.write(
            f"{RED}Downloads currently fail: Qobuz changed their request-"
            "signing scheme in April 2026. See README.\n"
        )
        sys.exit(3)

    except KeyboardInterrupt:
        logger.info(
            f"{RED}Interrupted by user\n{YELLOW}Already downloaded items will "
            "be skipped if you try to download the same releases again."
        )

    finally:
        _remove_leftovers(qobuz.directory)


def _initial_checks():
    if not os.path.isdir(CONFIG_PATH) or not os.path.isfile(CONFIG_FILE):
        os.makedirs(CONFIG_PATH, exist_ok=True)
        _reset_config(CONFIG_FILE)

    if len(sys.argv) < 2:
        sys.exit(qobuz_dl_args().print_help())


_REDACTED_KEYS = frozenset({"user_auth_token", "secrets", "password"})
_REDACTION_SENTINEL = "***REDACTED***"


def _redact_config_text(text):
    """Return `text` with secret-bearing config values replaced.

    Round-trips through `configparser` (rather than regex on lines) so
    that multi-line continuation values for sensitive keys get fully
    redacted, not just their first line. Targets `user_auth_token`,
    `secrets`, and the legacy `password` key. `app_id` is intentionally
    left visible (it's public — embedded in play.qobuz.com's bundle.js).
    """
    parser = configparser.ConfigParser()
    try:
        parser.read_string(text)
    except configparser.Error:
        # Fall back to regex over lines so we still redact best-effort
        # rather than echoing a malformed config raw.
        pattern = re.compile(
            r"^(\s*(?:" + "|".join(sorted(_REDACTED_KEYS)) + r")\s*=\s*).+$",
            re.MULTILINE | re.IGNORECASE,
        )
        return pattern.sub(r"\1" + _REDACTION_SENTINEL, text)

    for section in (parser.default_section, *parser.sections()):
        for key in list(parser[section]):
            if key.lower() in _REDACTED_KEYS and parser[section][key]:
                parser[section][key] = _REDACTION_SENTINEL

    buf = io.StringIO()
    parser.write(buf)
    return buf.getvalue()


_LEGACY_AUTH_MIGRATION_MSG = (
    f"{RED}Email/password authentication is no longer supported by Qobuz "
    "(deprecated server-side in April 2026).\n"
    f"{YELLOW}Run `qobuz-dl --reset` to set up token-based login (you'll "
    "need user_id and user_auth_token from play.qobuz.com).\n"
)

_NO_CREDENTIALS_MSG = (
    f"{RED}No credentials found in config.\n"
    f"{YELLOW}Run `qobuz-dl --reset` to enter your user_id and user_auth_token.\n"
)

_CORRUPT_CONFIG_MSG = (
    f"{RED}Config file is corrupt or missing required keys ({{error_type}}).\n"
    f"{YELLOW}Run `qobuz-dl --reset` to recreate it, or `qobuz-dl --show-config` "
    "to inspect (secrets redacted).\n"
)


def _show_config(show_secrets):
    """Print CONFIG_FILE to stdout. Used by --show-config; deliberately
    independent of the strict config-load so it works even when the
    config is corrupt (the case users most need it for)."""
    print(f"Configuration: {CONFIG_FILE}\nDatabase: {QOBUZ_DB}\n---")
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as exc:
        sys.stderr.write(f"{RED}Could not read config file: {type(exc).__name__}\n")
        sys.exit(2)
    if not show_secrets:
        text = _redact_config_text(text)
    print(text)


def _purge_db():
    try:
        os.remove(QOBUZ_DB)
    except FileNotFoundError:
        pass
    sys.exit(f"{GREEN}The database was deleted.")


def main():
    # Configure root logger here (not at module import) so importing
    # `qobuz_dl` as a library doesn't clobber the caller's logging setup.
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    _initial_checks()

    arguments = qobuz_dl_args().parse_args()

    # Maintenance flags must work BEFORE the strict config-load, so a user
    # with a corrupt config can still --reset / --show-config / --purge to
    # diagnose and recover.
    if arguments.reset:
        sys.exit(_reset_config(CONFIG_FILE))

    if arguments.show_config:
        _show_config(arguments.show_secrets)
        sys.exit()

    if arguments.purge:
        _purge_db()

    config = configparser.ConfigParser()
    try:
        config.read(CONFIG_FILE, encoding="utf-8")
        defaults = config["DEFAULT"]
        user_id = defaults.get("user_id", "")
        user_auth_token = defaults.get("user_auth_token", "")
        legacy_email = defaults.get("email", "")
        legacy_password = defaults.get("password", "")
        default_folder = defaults["default_folder"]
        default_limit = defaults["default_limit"]
        default_quality = defaults["default_quality"]
        no_m3u = config.getboolean("DEFAULT", "no_m3u")
        albums_only = config.getboolean("DEFAULT", "albums_only")
        no_fallback = config.getboolean("DEFAULT", "no_fallback")
        og_cover = config.getboolean("DEFAULT", "og_cover")
        embed_art = config.getboolean("DEFAULT", "embed_art")
        no_cover = config.getboolean("DEFAULT", "no_cover")
        no_database = config.getboolean("DEFAULT", "no_database")
        app_id = defaults["app_id"]
        smart_discography = config.getboolean("DEFAULT", "smart_discography")
        folder_format = defaults["folder_format"]
        track_format = defaults["track_format"]
        secrets = [s for s in defaults["secrets"].split(",") if s]
    except (KeyError, ValueError, UnicodeDecodeError, configparser.Error) as error:
        # KeyError: required option missing.
        # ValueError: getboolean() / int() coercion failed (e.g. no_cover = maybe).
        # UnicodeDecodeError: non-UTF-8 bytes in the file (e.g. saved by a
        #   Windows editor with cp1252) — caught here because configparser's
        #   parsing error includes the offending source line.
        # configparser.Error: malformed INI syntax (ParsingError, etc.) —
        #   its str() can echo the offending line, which may include a
        #   `user_auth_token = ...` value, so we ONLY surface the type.
        sys.stderr.write(_CORRUPT_CONFIG_MSG.format(error_type=type(error).__name__))
        sys.exit(2)

    # Re-parse args with config defaults applied.
    arguments = qobuz_dl_args(default_quality, default_limit, default_folder).parse_args()

    # Auth dispatch: token > legacy email/password > nothing.
    if not (user_id and user_auth_token):
        if legacy_email or legacy_password:
            sys.stderr.write(_LEGACY_AUTH_MIGRATION_MSG)
        else:
            sys.stderr.write(_NO_CREDENTIALS_MSG)
        sys.exit(2)

    qobuz = QobuzDL(
        arguments.directory,
        arguments.quality,
        arguments.embed_art or embed_art,
        ignore_singles_eps=arguments.albums_only or albums_only,
        no_m3u_for_playlists=arguments.no_m3u or no_m3u,
        quality_fallback=not (arguments.no_fallback or no_fallback),
        cover_og_quality=arguments.og_cover or og_cover,
        no_cover=arguments.no_cover or no_cover,
        downloads_db=None if no_database or arguments.no_db else QOBUZ_DB,
        folder_format=arguments.folder_format or folder_format,
        track_format=arguments.track_format or track_format,
        smart_discography=arguments.smart_discography or smart_discography,
    )
    try:
        qobuz.initialize_client_with_token(user_id, user_auth_token, app_id, secrets)
    except (AuthenticationError, InvalidAppIdError, IneligibleError) as exc:
        # The qopy AuthenticationError messages are deliberately scrubbed
        # of token-bearing URLs and already point users at --reset, so str(exc)
        # is safe to echo. Avoids tracebacks for the very common "stale token"
        # case (tokens are long-lived but server-revocable).
        sys.stderr.write(f"{RED}{exc}\n")
        sys.exit(2)

    if arguments.command in {"dl", "fun", "lucky"} and getattr(
        qobuz.client, "sec", None
    ) is None:
        sys.stderr.write(
            f"{RED}Downloads currently fail: Qobuz changed their request-"
            "signing scheme in April 2026 and qobuz-dl hasn't reimplemented "
            "the new SHA-256 + HKDF signing yet.\n"
            f"{YELLOW}Login and metadata/search work; downloads do not. "
            "See the README for the tracking issue.\n"
        )
        sys.exit(3)

    _handle_commands(qobuz, arguments)


if __name__ == "__main__":
    sys.exit(main())
