"""F10: TOTP two-factor authentication.

Covers the RFC 6238 TOTP primitive, the post-password verification step enforced
on login, and self-service enable/disable management.
"""
import base64


def _pending_secret(app, client):
    """Read the in-session pending TOTP secret minted by the enable page."""
    with app.app_context():
        raw = client.get_cookie('session').value
        serializer = app.session_interface.get_signing_serializer(app)
        data = serializer.loads(raw, max_age=0)
    return data.get('mfa_pending_secret')


def _login(app, client, username='probe', password='Str0ng!Passw0rd!'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


# --- TOTP primitive --------------------------------------------------------


def test_totp_matches_rfc6238_vector():
    from app import totp
    # RFC 6238 Appendix B: the canonical 20-byte key "12345678901234567890"
    # yields code 94287082 (8-digit) at T=59s; our 6-digit codes take the low
    # six digits -> 287082.
    secret = base64.b32encode(b'12345678901234567890').decode()
    assert totp.totp_code(secret, now=59.0) == '287082'


def test_totp_verify_accepts_valid_and_rejects_others(app):
    from app import totp
    secret = totp.generate_secret()
    code = totp.totp_code(secret)
    assert totp.verify_totp(secret, code) is True
    assert totp.verify_totp(secret, '000000') is False
    assert totp.verify_totp(secret, '') is False
    assert totp.verify_totp('', code) is False


def test_totp_provisioning_uri(app):
    from app import totp
    secret = totp.generate_secret()
    uri = totp.provisioning_uri(secret, 'alice@example.com')
    assert uri.startswith('otpauth://totp/')
    assert f'secret={secret}' in uri


# --- Login two-step --------------------------------------------------------


def test_login_without_mfa_proceeds_directly(app):
    from app.models import User
    with app.app_context():
        u = User(username='nomfa', email='nomfa@example.com')
        u.set_password('Str0ng!Passw0rd!')
        db_add_commit(app, u)
    c = app.test_client()
    r = c.post('/login', data={'username': 'nomfa', 'password': 'Str0ng!Passw0rd!'},
               follow_redirects=False)
    assert r.status_code == 302
    assert r.headers['Location'].endswith('/dashboard')


def test_login_with_mfa_requires_second_factor(app):
    from app.models import User
    secret = base64.b32encode(b'abcdefghijklmnop').decode()
    with app.app_context():
        u = User(username='mfaf', email='mfaf@example.com')
        u.set_password('Str0ng!Passw0rd!')
        u.totp_secret = secret
        db_add_commit(app, u)
    c = app.test_client()
    r = c.post('/login', data={'username': 'mfaf', 'password': 'Str0ng!Passw0rd!'},
               follow_redirects=False)
    assert r.status_code == 302
    assert r.headers['Location'].endswith('/login/two-factor')


def test_login_with_mfa_correct_code_logs_in(app):
    from app.models import User
    secret = base64.b32encode(b'abcdefghijklmnop').decode()
    with app.app_context():
        u = User(username='mm', email='mm@example.com')
        u.set_password('Str0ng!Passw0rd!')
        u.totp_secret = secret
        db_add_commit(app, u)
    from app import totp
    code = totp.totp_code(secret)
    c = app.test_client()
    c.post('/login', data={'username': 'mm', 'password': 'Str0ng!Passw0rd!'},
           follow_redirects=False)
    r = c.post('/login/two-factor', data={'code': code}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers['Location'].endswith('/dashboard')
    assert c.get('/dashboard').status_code == 200


def test_login_with_mfa_wrong_code_rejected(app):
    from app.models import User
    secret = base64.b32encode(b'abcdefghijklmnop').decode()
    with app.app_context():
        u = User(username='mw', email='mw@example.com')
        u.set_password('Str0ng!Passw0rd!')
        u.totp_secret = secret
        db_add_commit(app, u)
    c = app.test_client()
    c.post('/login', data={'username': 'mw', 'password': 'Str0ng!Passw0rd!'},
           follow_redirects=False)
    r = c.post('/login/two-factor', data={'code': '000000'}, follow_redirects=True)
    assert r.status_code == 200
    # Not logged in: dashboard bounces back to login.
    assert c.get('/dashboard').status_code == 302


def test_two_factor_step_without_pending_session_redirects(app):
    r = app.test_client().get('/login/two-factor')
    assert r.status_code == 302
    assert r.headers['Location'].endswith('/login')


# --- Enable / disable management -------------------------------------------


def test_two_factor_settings_requires_login(app):
    r = app.test_client().get('/settings/two-factor')
    assert r.status_code == 302


def test_enable_two_factor_flow(app):
    from app.models import User
    with app.app_context():
        u = User(username='en', email='en@example.com')
        u.set_password('Str0ng!Passw0rd!')
        db_add_commit(app, u)
    c = app.test_client()
    _login(app, c, 'en')

    # Disabled initially -> GET mints a pending secret.
    r = c.get('/settings/two-factor')
    assert r.status_code == 200
    secret = _pending_secret(app, c)
    assert secret

    # Wrong code is rejected and does not enable.
    r = c.post('/settings/two-factor', data={'code': '000000'}, follow_redirects=False)
    assert r.status_code == 200
    from app.models import User as U
    with app.app_context():
        assert U.query.filter_by(username='en').first().totp_secret is None

    # Correct code enables MFA.
    from app import totp
    code = totp.totp_code(secret)
    r = c.post('/settings/two-factor', data={'code': code}, follow_redirects=False)
    assert r.status_code == 302  # redirected after success
    with app.app_context():
        assert U.query.filter_by(username='en').first().totp_secret == secret

    # Now login enforces the second factor.
    c2 = app.test_client()
    c2.post('/login', data={'username': 'en', 'password': 'Str0ng!Passw0rd!'},
            follow_redirects=False)
    assert c2.get('/dashboard').status_code == 302


def test_disable_two_factor_requires_password(app):
    from app import totp
    from app.models import User
    secret = base64.b32encode(b'abcdefghijklmnop').decode()
    with app.app_context():
        u = User(username='di', email='di@example.com')
        u.set_password('Str0ng!Passw0rd!')
        u.totp_secret = secret
        db_add_commit(app, u)
    c = app.test_client()
    # Log in *through* the second-factor step so the session is fully established.
    c.post('/login', data={'username': 'di', 'password': 'Str0ng!Passw0rd!'},
           follow_redirects=False)
    c.post('/login/two-factor', data={'code': totp.totp_code(secret)},
           follow_redirects=True)

    # Wrong password is rejected; secret stays.
    r = c.post('/settings/two-factor', data={'current_password': 'wrong'},
               follow_redirects=False)
    assert r.status_code == 200
    with app.app_context():
        assert User.query.filter_by(username='di').first().totp_secret == secret

    # Correct password disables; login then proceeds without a second factor.
    r = c.post('/settings/two-factor',
               data={'current_password': 'Str0ng!Passw0rd!'},
               follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        assert User.query.filter_by(username='di').first().totp_secret is None
    c2 = app.test_client()
    c2.post('/login', data={'username': 'di', 'password': 'Str0ng!Passw0rd!'},
            follow_redirects=False)
    assert c2.get('/dashboard').status_code == 200


# --- helpers ---------------------------------------------------------------


def db_add_commit(app, *models):
    from app import db as sql_db
    with app.app_context():
        for m in models:
            sql_db.session.add(m)
        sql_db.session.commit()
