"""Shared email utilities for Super-Bot email features."""

from __future__ import annotations

import os
import smtplib
import ssl
from contextlib import contextmanager
from typing import Iterator

from dotenv import load_dotenv

from utils import logger

load_dotenv()


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")

_raw_smtp_password = os.getenv("SMTP_PASSWORD", "")
_allow_password_spaces = _as_bool(os.getenv("SMTP_ALLOW_PASSWORD_SPACES"), default=False)

if _raw_smtp_password and (" " in _raw_smtp_password) and not _allow_password_spaces:
    logger.info(
        "Stripping spaces from SMTP_PASSWORD for compatibility. "
        "Set SMTP_ALLOW_PASSWORD_SPACES=1 to disable."
    )
    SMTP_PASSWORD = _raw_smtp_password.replace(" ", "")
else:
    SMTP_PASSWORD = _raw_smtp_password

SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", SMTP_USERNAME)
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Super-Bot Alerts")

SMTP_USE_SSL = _as_bool(os.getenv("SMTP_USE_SSL"), default=False)
SMTP_USE_TLS = _as_bool(os.getenv("SMTP_USE_TLS"), default=not SMTP_USE_SSL)
SMTP_REQUIRE_AUTH = _as_bool(os.getenv("SMTP_REQUIRE_AUTH"), default=True)
SMTP_TIMEOUT = float(os.getenv("SMTP_TIMEOUT", "30"))


class EmailConfigurationError(RuntimeError):
    """Raised when the email system is not properly configured."""


def is_email_configured() -> bool:
    """Return True if email sending is configured."""
    if SMTP_REQUIRE_AUTH:
        return bool(SMTP_USERNAME and SMTP_PASSWORD)
    return bool(SMTP_HOST and SMTP_PORT)


@contextmanager
def smtp_connection() -> Iterator[smtplib.SMTP]:
    """
    Context manager yielding an SMTP connection with proper security.

    Raises:
        EmailConfigurationError: If SMTP settings are incomplete.
    """
    if not SMTP_HOST:
        raise EmailConfigurationError("SMTP_HOST is not configured.")
    if not SMTP_PORT:
        raise EmailConfigurationError("SMTP_PORT is not configured.")

    if SMTP_REQUIRE_AUTH and (not SMTP_USERNAME or not SMTP_PASSWORD):
        raise EmailConfigurationError("SMTP credentials are not configured.")

    server: smtplib.SMTP | None = None
    try:
        context = ssl.create_default_context()
        if SMTP_USE_SSL or int(SMTP_PORT) == 465:
            server = smtplib.SMTP_SSL(
                SMTP_HOST,
                SMTP_PORT,
                context=context,
                timeout=SMTP_TIMEOUT,
            )
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT)
            if SMTP_USE_TLS:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()

        if SMTP_REQUIRE_AUTH:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)

        yield server
    except Exception as exc:
        logger.error(f"SMTP connection failure: {exc}")
        raise
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception as exc:
                logger.debug(f"Failed to close SMTP connection cleanly: {exc}")


__all__ = [
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "SMTP_FROM_EMAIL",
    "SMTP_FROM_NAME",
    "SMTP_USE_SSL",
    "SMTP_USE_TLS",
    "SMTP_REQUIRE_AUTH",
    "SMTP_TIMEOUT",
    "EmailConfigurationError",
    "is_email_configured",
    "smtp_connection",
]


