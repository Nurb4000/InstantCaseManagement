"""F10: TOTP (RFC 6238) implementation for two-factor authentication.

Dependency-free: uses only the standard library (hmac/hashlib/base64/time) so
no extra package (e.g. pyotp) is required. Codes are 6 digits on a 30 second
step; verification tolerates a +/-1 step of clock skew (a 60 second window).

The secret is a base32 string stored on ``User.totp_secret`` and shared with an
authenticator app via an ``otpauth://`` provisioning URI / QR code.
"""
import base64
import hashlib
import hmac
import os
import time
from urllib.parse import quote

TOTP_DIGITS = 6
TOTP_STEP = 30  # seconds per code


def generate_secret(num_bytes=10):
    """Return a fresh random base32 secret (RFC 4648, unpadded)."""
    return base64.b32encode(os.urandom(num_bytes)).decode('ascii').rstrip('=')


def _decode_secret(secret):
    """Base32-decode a secret, restoring any missing padding."""
    return base64.b32decode(secret + '=' * ((8 - len(secret) % 8) % 8))


def _hotp(key, counter, digits=TOTP_DIGITS):
    """RFC 4226 one-time password for the given counter (compact HMAC-OTP)."""
    digest = hmac.new(key, counter.to_bytes(8, 'big'), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (
        (digest[offset] & 0x7F) << 24
        | (digest[offset + 1] & 0xFF) << 16
        | (digest[offset + 2] & 0xFF) << 8
        | (digest[offset + 3] & 0xFF)
    )
    return str(value % (10 ** digits)).zfill(digits)


def totp_code(secret, now=None, step=TOTP_STEP, digits=TOTP_DIGITS):
    """Return the current TOTP code for ``secret`` (mainly for tests)."""
    if now is None:
        now = time.time()
    counter = int(now) // step
    return _hotp(_decode_secret(secret), counter, digits)


def verify_totp(secret, code, now=None, window=1, step=TOTP_STEP, digits=TOTP_DIGITS):
    """Validate ``code`` against ``secret``, allowing +/-``window`` steps.

    Returns False for empty input so a missing/blank submission never matches.
    """
    if not secret or not code:
        return False
    code = str(code).strip()
    key = _decode_secret(secret)
    if now is None:
        now = time.time()
    counter = int(now) // step
    for delta in range(-window, window + 1):
        if _hotp(key, counter + delta, digits) == code:
            return True
    return False


def provisioning_uri(secret, account_name, issuer='Case-Tool'):
    """Build an ``otpauth://totp/...`` URI for QR display / manual entry."""
    params = f'secret={secret}&issuer={quote(issuer)}&digits={TOTP_DIGITS}&step={TOTP_STEP}'
    return f'otpauth://totp/{quote(issuer)}:{quote(account_name)}?{params}'
