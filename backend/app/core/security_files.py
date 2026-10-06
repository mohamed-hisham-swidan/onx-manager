"""Security file permission hardening utilities."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.core.exceptions import SecurityPermissionError

logger = logging.getLogger(__name__)


def ensure_private_key_permissions(
    path: Path | str,
    allow_insecure: bool | None = None,
) -> None:
    """Ensure private key file permissions are restricted to owner only (0o600 or 0o400).

    On POSIX, if permissions allow group or other access ((mode & 0o077) != 0), attempts to
    chmod 0o600. If the file remains too open, logs a CRITICAL error and raises
    SecurityPermissionError unless allow_insecure is True (or allow_insecure_keys is enabled
    in AppSettings).
    On Windows (os.name == 'nt'), POSIX file mode bits do not apply, so this check is skipped.
    """
    if os.name == "nt":
        logger.info("Skipping POSIX key file permission check on Windows: %s", path)
        return

    p = Path(path)
    if not p.exists():
        return

    st = p.stat()
    mode = st.st_mode & 0o777
    if (mode & 0o077) == 0:
        return

    try:
        os.chmod(p, 0o600)
    except OSError as exc:
        logger.warning("Failed to chmod 0600 on key file %s: %s", p, exc)

    new_mode = p.stat().st_mode & 0o777
    if (new_mode & 0o077) != 0:
        logger.critical(
            "Insecure file permissions on key file %s (mode %o, expected 0600)",
            p,
            new_mode,
        )
        if allow_insecure is None:
            try:
                from app.core.config import ConfigFactory

                allow_insecure = ConfigFactory.global_settings().allow_insecure_keys
            except Exception:
                allow_insecure = False
        if not allow_insecure:
            raise SecurityPermissionError(
                f"Insecure file permissions on key file {p} (mode {oct(new_mode)}, expected 0600)"
            )
