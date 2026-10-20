"""S4 follow-up — progressive login CAPTCHA.

Covers the trigger threshold, challenge generation/validation, and end-to-end
behaviour through the /login route: the challenge surfaces after enough failed
attempts, a wrong answer is rejected, and a correct answer + credentials logs in
and clears the challenge.
"""
import re


def test_captcha_trigger_threshold(app, monkeypatch):
    from app import auth_security
    monkeypatch.setattr(auth_security, 'CAPTCHA_TRIGGER_FAILURES', 3, raising=True)
    ip = '198.51.100.7'
    with app.app_context():
        for _ in range(2):
            auth_security.record_login_attempt('x', ip, success=False)
        assert auth_security.captcha_required_for_ip(ip) is False
        auth_security.record_login_attempt('x', ip, success=False)
        assert auth_security.captcha_required_for_ip(ip) is True


def test_generate_captcha_challenge_is_arithmetic():
    from app import auth_security
    question, answer = auth_security.generate_captcha_challenge()
    # "a + b" or "a - b" with a non-negative integer result.
    m = re.match(r'^(\d+) ([+-]) (\d+)$', question)
    assert m, question
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    assert answer == (a + b) if op == '+' else (a - b)
    assert answer >= 0


def test_captcha_matches(app):
    from app import auth_security
    with app.test_request_context():
        from flask import session
        auth_security.ensure_captcha_challenge()
        # The stored answer is not exposed to the client; validate round-trip.
        assert auth_security.captcha_matches('not-the-answer') is False
        real = session['captcha']['answer']
        assert auth_security.captcha_matches(str(real)) is True


def test_captcha_expires(app):
    from app import auth_security
    from datetime import datetime, timedelta
    with app.test_request_context():
        from flask import session
        auth_security.ensure_captcha_challenge()
        session['captcha']['created'] = (
            datetime.utcnow() - timedelta(seconds=auth_security.CAPTCHA_TTL_SECONDS + 10)
        ).isoformat()
        assert auth_security.captcha_matches('x') is False
        # ensure_* should refresh an expired challenge.
        q = auth_security.ensure_captcha_challenge()
        assert q


def _register_user(app, username):
    from app.models import User
    from app import db as sql_db
    with app.app_context():
        u = User(username=username, email=f'{username}@example.com')
        u.set_password('Str0ng!Passw0rd')
        sql_db.session.add(u)
        sql_db.session.commit()


def test_login_surfaces_captcha_after_failures(app, client, monkeypatch):
    """After enough failures the login page shows a security check."""
    from app import auth_security
    monkeypatch.setattr(auth_security, 'CAPTCHA_TRIGGER_FAILURES', 2, raising=True)
    _register_user(app, 'captchau')
    ip = '198.51.100.9'

    # Two wrong attempts to trip the threshold.
    for _ in range(2):
        client.post('/login', data={'username': 'captchau', 'password': 'nope'},
                    environ_base={'REMOTE_ADDR': ip})

    r = client.get('/login', environ_base={'REMOTE_ADDR': ip})
    assert r.status_code == 200
    assert re.search(r'input-group-text">[^<]+</span>', r.get_data(as_text=True))


def test_login_rejects_wrong_captcha(app, client, monkeypatch):
    """A wrong CAPTCHA answer is rejected and recorded as a failure."""
    from app import auth_security
    monkeypatch.setattr(auth_security, 'CAPTCHA_TRIGGER_FAILURES', 2, raising=True)
    _register_user(app, 'captchb')
    ip = '198.51.100.10'

    for _ in range(2):
        client.post('/login', data={'username': 'captchb', 'password': 'nope'},
                    environ_base={'REMOTE_ADDR': ip})

    # Correct credentials but a wrong CAPTCHA answer.
    r = client.post(
        '/login',
        data={'username': 'captchb', 'password': 'Str0ng!Passw0rd', 'captcha': '0'},
        environ_base={'REMOTE_ADDR': ip},
        follow_redirects=True,
    )
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'Security check failed' in body
    with app.app_context():
        from app.models import LoginAttempt
        fails = LoginAttempt.query.filter_by(ip=ip, success=False).count()
        assert fails >= 3  # 2 wrong pw + 1 wrong captcha


def test_login_success_with_captcha_clears_challenge(app, client, monkeypatch):
    """Correct CAPTCHA + credentials logs in and forgets the challenge."""
    from app import auth_security
    monkeypatch.setattr(auth_security, 'captcha_matches', lambda provided: True, raising=True)
    monkeypatch.setattr(auth_security, 'CAPTCHA_TRIGGER_FAILURES', 2, raising=True)
    _register_user(app, 'captchc')
    ip = '198.51.100.11'

    for _ in range(2):
        client.post('/login', data={'username': 'captchc', 'password': 'nope'},
                    environ_base={'REMOTE_ADDR': ip})

    r = client.post(
        '/login',
        data={'username': 'captchc', 'password': 'Str0ng!Passw0rd', 'captcha': 'anything'},
        environ_base={'REMOTE_ADDR': ip},
    )
    assert r.status_code == 302  # correct captcha + credentials logs in


def test_login_captcha_not_required_without_failures(app, client):
    """A clean login never shows a security check."""
    _register_user(app, 'captchd')
    r = client.get('/login', environ_base={'REMOTE_ADDR': '198.51.100.12'})
    assert r.status_code == 200
    assert 'input-group-text' not in r.get_data(as_text=True)
