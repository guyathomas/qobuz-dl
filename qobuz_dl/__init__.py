"""Public package surface for qobuz-dl.

Migration note (0.9.10.0): the legacy `Client(email, pwd, app_id, secrets)`
constructor was removed because Qobuz disabled email/password auth
server-side in April 2026. Use `Client.from_token(...)` instead.
The legacy `QobuzDL.initialize_client(...)` was renamed to
`initialize_client_with_token(...)`.

If you were importing `qobuz_dl.Client` directly, the constructor now
takes `(app_id, secrets)` and does not authenticate; call
`Client.from_token(user_id, user_auth_token, app_id, secrets)` to get a
ready-to-use client.
"""

from .qopy import Client
from .cli import main

__all__ = ["Client", "main"]
