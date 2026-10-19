"""S6 — Optional encryption of sensitive OrgSetting values (e.g. SMTP password)
at rest in the database.

Design:
  * Uses Fernet (symmetric, authenticated encryption).
  * Key comes from the ``SMTP_ENCRYPTION_KEY`` environment variable (a base64
    urlsafe-512 Fernet key, e.g. produced by ``fernet.generate_key()``).
  * Fail-open + loud: if no key is configured, values are stored/returned as
    plaintext and a one-time warning is logged. This keeps existing deployments
    working while making the insecure posture visible.
  * Legacy-tolerant decryption: values that were never encrypted (or were
    encrypted under a different key) are returned unchanged rather than raising,
    so a rotated/missing key degrades gracefully instead of breaking mail.

Because encryption is opt-in via env, operators who want S6 actually enforced
should set SMTP_ENCRYPTION_KEY and treat an unset key as a config error in their
deploy manifest.
"""
import os
import warnings

from cryptography.fernet import Fernet

_warned = False


def _key():
    raw = os.environ.get('SMTP_ENCRYPTION_KEY')
    if not raw:
        return None
    # Fernet keys are base64 urlsafe 44-char strings; encode for Fernet.
    return raw.encode()


def _warn_once(message):
    global _warned
    if not _warned:
        _warned = True
        warnings.warn(message, stacklevel=2)
        try:
            from flask import current_app
            current_app.logger.warning(message)
        except Exception:
            print(f"[security] {message}")


def encrypt_plaintext(plaintext):
    """Encrypt ``plaintext``; return unchanged (with warning) if no key set."""
    if not plaintext:
        return plaintext
    key = _key()
    if not key:
        _warn_once('SMTP_ENCRYPTION_KEY not set — sensitive values stored in plaintext.')
        return plaintext
    return Fernet(key).encrypt(plaintext.encode()).decode()


def decrypt_or_plain(token):
    """Decrypt a stored token; fall back to the raw value if undecryptable
    (legacy plaintext, missing key, or rotated key)."""
    if not token:
        return token
    key = _key()
    if not key:
        return token
    try:
        return Fernet(key).decrypt(token.encode()).decode()
    except Exception:
        # Either legacy plaintext or a key rotation we can't recover from.
        # Return as-is so the caller sees the stored value rather than crashing.
        return token
