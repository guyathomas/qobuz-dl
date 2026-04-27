"""Atomic config writer used for `~/.config/qobuz-dl/config.ini`.

The config holds a long-lived `user_auth_token`; a partial write would
corrupt the only credentials store on disk. Idiom:

  1. tempfile.NamedTemporaryFile in the *same directory* as the target
  2. parser.write(...), flush, fsync the file fd
  3. close before os.replace (required on Windows)
  4. os.replace (atomic on POSIX; works on Windows too)
  5. chmod 0o600 on POSIX (no-op on Windows)
  6. fsync the parent directory on POSIX so the rename's directory entry
     is durable across power loss
  7. on any exception before os.replace: best-effort unlink the temp file,
     then re-raise
"""

import contextlib
import os
import tempfile


def atomic_write_config(path, parser):
    target_dir = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(target_dir, exist_ok=True)

    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=target_dir,
        prefix=".config-",
        suffix=".tmp",
        delete=False,
    )
    tmp_name = tmp.name
    try:
        parser.write(tmp)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.close()
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise

    if os.name != "nt":
        os.chmod(path, 0o600)
        # Make the rename's directory entry durable across power loss.
        # Best-effort: some filesystems (e.g. cifs) reject directory fsync.
        try:
            dirfd = os.open(target_dir, os.O_RDONLY)
        except OSError:
            return
        try:
            with contextlib.suppress(OSError):
                os.fsync(dirfd)
        finally:
            os.close(dirfd)
