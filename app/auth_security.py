"""S4 — Login brute-force protection.

Strategy: per-IP progressive (exponential) delay based on recent failed
attempts, plus a hard cap that rejects further attempts for a short cooldown.

Why keyed on IP rather than username:
    Locking out by username lets any attacker freeze a victim's account (a
    trivial denial-of-service). Keying on IP slows brute force against *any*
    account from a source without permanently locking out a specific user.

Caveat:
    Users behind a shared IP (NAT, office egress, VPN) share the budget. For an
    internal authenticated tool this is an acceptable trade-off; if that is not
    true for your deployment, raise the hard-cap threshold accordingly.

Follow-up (progressive CAPTCHA):
    The IP budget is defeated by IP rotation/botnets and offers no protection
    to a victim sharing an egress IP. A progressive arithmetical CAPTCHA,
    surfaced once an IP accumulates enough failures, breaks automated brute
    force regardless of IP topology without reintroducing the account-DoS
    vector of username lockouts. It is server-side (challenge answer stored in
    the signed session) so it works with any client and is trivially testable.

All behaviour is tunable via environment variables so ops can tune to their
threat model without code changes.
"""
import os
import random
import time
from datetime import datetime, timedelta

from flask import current_app, session
from app import db
from app.models import LoginAttempt

# Tunables (all optional; sensible defaults below).
FAIL_WINDOW_SECONDS = int(os.environ.get('LOGIN_FAIL_WINDOW_MIN', '15')) * 60
DELAY_BASE_SECONDS = float(os.environ.get('LOGIN_FAIL_DELAY_BASE_S', '1'))
DELAY_MAX_SECONDS = float(os.environ.get('LOGIN_FAIL_DELAY_MAX_S', '30'))
# After this many failures in the window, reject attempts outright for the
# cooldown period instead of merely delaying.
HARD_FAIL_CAP = int(os.environ.get('LOGIN_FAIL_HARD_CAP', '8'))
COOLDOWN_SECONDS = int(os.environ.get('LOGIN_FAIL_COOLDOWN_S', '300'))  # 5 min
# Keep at most this many audit rows to bound table growth.
MAX_ATTEMPT_ROWS = int(os.environ.get('LOGIN_FAIL_MAX_ROWS', '2000'))


def recent_failures_by_ip(ip, now=None):
    now = now or datetime.utcnow()
    cutoff = now - timedelta(seconds=FAIL_WINDOW_SECONDS)
    return LoginAttempt.query.filter(
        LoginAttempt.ip == ip,
        LoginAttempt.success.is_(False),
        LoginAttempt.timestamp >= cutoff,
    ).count()


def login_delay_seconds(ip):
    """Return the progressive delay (seconds) to apply before processing a login."""
    failures = recent_failures_by_ip(ip)
    if failures <= 0:
        return 0.0
    # Exponential backoff, capped so a stuck client can't be delayed forever.
    return min(DELAY_BASE_SECONDS * (2 ** (failures - 1)), DELAY_MAX_SECONDS)


def ip_in_hard_cap(ip, now=None):
    """True if the IP has hit the hard-cap threshold and is still in cooldown."""
    now = now or datetime.utcnow()
    cutoff = now - timedelta(seconds=COOLDOWN_SECONDS)
    count = LoginAttempt.query.filter(
        LoginAttempt.ip == ip,
        LoginAttempt.success.is_(False),
        LoginAttempt.timestamp >= cutoff,
    ).count()
    return count >= HARD_FAIL_CAP


def record_login_attempt(username, ip, success):
    row = LoginAttempt(username=username, ip=ip, success=bool(success))
    db.session.add(row)
    db.session.commit()
    prune_login_attempts()


def prune_login_attempts():
    """Bound table growth: drop the oldest rows beyond MAX_ATTEMPT_ROWS."""
    try:
        total = LoginAttempt.query.count()
    except Exception:
        return
    if total <= MAX_ATTEMPT_ROWS:
        return
    to_delete = total - MAX_ATTEMPT_ROWS
    ids = (
        db.session.query(LoginAttempt.id)
        .order_by(LoginAttempt.timestamp.asc())
        .limit(to_delete)
        .all()
    )
    LoginAttempt.query.filter(LoginAttempt.id.in_([i[0] for i in ids])).delete(
        synchronize_session=False
    )
    db.session.commit()


def apply_login_delay(ip):
    """Sleep for the computed delay. Returns True if the caller should abort
    early because the IP is in hard-cap cooldown."""
    if ip_in_hard_cap(ip):
        return True
    delay = login_delay_seconds(ip)
    if delay > 0:
        time.sleep(delay)
    return False


# --- Progressive CAPTCHA (S4 follow-up) -------------------------------------
#
# Surfaced once an IP accumulates CAPTCHA_TRIGGER_FAILURES failures within the
# failure window. The challenge/answer live in the signed session, so there is
# no client-side dependency and no way to scrape the answer from the HTML.

CAPTCHA_TRIGGER_FAILURES = int(os.environ.get('LOGIN_CAPTCHA_AFTER', '5'))
CAPTCHA_TTL_SECONDS = int(os.environ.get('LOGIN_CAPTCHA_TTL_S', '120'))


def captcha_required_for_ip(ip, now=None):
    """True if the IP has enough recent failures to warrant a CAPTCHA."""
    now = now or datetime.utcnow()
    cutoff = now - timedelta(seconds=FAIL_WINDOW_SECONDS)
    count = LoginAttempt.query.filter(
        LoginAttempt.ip == ip,
        LoginAttempt.success.is_(False),
        LoginAttempt.timestamp >= cutoff,
    ).count()
    return count >= CAPTCHA_TRIGGER_FAILURES


def generate_captcha_challenge():
    """Return (question_text, answer) for a simple +/- arithmetic problem."""
    a = random.randint(1, 12)
    b = random.randint(1, 12)
    if random.random() < 0.5:
        return f'{a} + {b}', a + b
    large, small = max(a, b), min(a, b)
    return f'{large} - {small}', large - small


def _captcha_is_valid(stored):
    if not stored or 'answer' not in stored or 'created' not in stored:
        return False
    try:
        created = datetime.fromisoformat(stored['created'])
    except (ValueError, TypeError):
        return False
    return (datetime.utcnow() - created).total_seconds() <= CAPTCHA_TTL_SECONDS


def ensure_captcha_challenge():
    """Return the current in-session challenge text, generating/refreshing one
    if none exists or it has expired."""
    stored = session.get('captcha')
    if _captcha_is_valid(stored):
        return stored['question']
    question, answer = generate_captcha_challenge()
    session['captcha'] = {
        'question': question,
        'answer': answer,
        'created': datetime.utcnow().isoformat(),
    }
    session.modified = True
    return question


def regenerate_captcha_challenge():
    """Discard the current challenge and mint a fresh one (on failure)."""
    session.pop('captcha', None)
    return ensure_captcha_challenge()


def captcha_matches(provided):
    """True if the submitted answer matches the valid in-session challenge."""
    stored = session.get('captcha')
    if not _captcha_is_valid(stored):
        return False
    return str(provided or '').strip() == str(stored['answer'])


def clear_captcha_for_session():
    """Forget the CAPTCHA after a successful login."""
    session.pop('captcha', None)
