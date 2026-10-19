"""Phase 2b security tests: S4 (login brute-force protection), S6 (SMTP
encryption at rest), plus S5/S8 regression checks."""
import os

import pytest
from cryptography.fernet import Fernet


# ---------------------------------------------------------------------------
# S4 — login brute-force protection
# ---------------------------------------------------------------------------

def test_delay_grows_with_failures(app):
    from app import auth_security
    auth_security.DELAY_MAX_SECONDS = 10_000  # don't actually sleep in this assertion
    ip = '203.0.113.10'
    with app.app_context():
        auth_security.record_login_attempt('bob', ip, success=False)
        d1 = auth_security.login_delay_seconds(ip)
        auth_security.record_login_attempt('bob', ip, success=False)
        d2 = auth_security.login_delay_seconds(ip)
    assert d2 > d1 > 0


def test_hard_cap_detects_threshold(app, monkeypatch):
    from app import auth_security
    monkeypatch.setattr(auth_security, 'HARD_FAIL_CAP', 3, raising=True)
    ip = '203.0.113.11'
    with app.app_context():
        assert auth_security.ip_in_hard_cap(ip) is False
        for _ in range(3):
            auth_security.record_login_attempt('bob', ip, success=False)
        assert auth_security.ip_in_hard_cap(ip) is True


def test_prune_bounds_table(app, monkeypatch):
    from app import auth_security
    monkeypatch.setattr(auth_security, 'MAX_ATTEMPT_ROWS', 5, raising=True)
    ip = '203.0.113.12'
    with app.app_context():
        for i in range(12):
            auth_security.record_login_attempt(f'u{i}', ip, success=True)
        assert auth_security.LoginAttempt.query.count() <= 5


def test_login_route_records_failed_attempt(app, client):
    from app.models import User, LoginAttempt
    from app import db as sql_db
    with app.app_context():
        u = User(username='zoe', email='zoe@example.com')
        u.set_password('Str0ng!Passw0rd')
        sql_db.session.add(u)
        sql_db.session.commit()
    client.post('/login', data={'username': 'zoe', 'password': 'wrong'},
                environ_base={'REMOTE_ADDR': '203.0.113.20'})
    with app.app_context():
        assert LoginAttempt.query.filter_by(ip='203.0.113.20', success=False).count() >= 1


def test_login_route_records_success(app, client):
    from app.models import User, LoginAttempt
    from app import db as sql_db
    with app.app_context():
        u = User(username='yan', email='yan@example.com')
        u.set_password('Str0ng!Passw0rd')
        sql_db.session.add(u)
        sql_db.session.commit()
    client.post('/login', data={'username': 'yan', 'password': 'Str0ng!Passw0rd'},
                environ_base={'REMOTE_ADDR': '203.0.113.21'})
    with app.app_context():
        assert LoginAttempt.query.filter_by(ip='203.0.113.21', success=True).count() >= 1


# ---------------------------------------------------------------------------
# S6 — SMTP password encryption at rest
# ---------------------------------------------------------------------------

def test_encrypt_roundtrip(monkeypatch):
    key = Fernet.generate_key()
    monkeypatch.setenv('SMTP_ENCRYPTION_KEY', key.decode())
    from app import crypto
    token = crypto.encrypt_plaintext('s3cr3t-pass')
    assert token != 's3cr3t-pass'
    assert crypto.decrypt_or_plain(token) == 's3cr3t-pass'


def test_fails_open_without_key(monkeypatch):
    monkeypatch.delenv('SMTP_ENCRYPTION_KEY', raising=False)
    from app import crypto
    # No key -> value stored/returned as plaintext (fail-open, loud elsewhere).
    assert crypto.encrypt_plaintext('plain-pw') == 'plain-pw'
    assert crypto.decrypt_or_plain('plain-pw') == 'plain-pw'


def test_legacy_plaintext_decrypt(app, monkeypatch):
    """A value encrypted under a different key (or legacy plaintext) must not
    raise — it degrades to the stored value."""
    key = Fernet.generate_key()
    monkeypatch.setenv('SMTP_ENCRYPTION_KEY', key.decode())
    from app import crypto
    legacy = 'never-encrypted'
    assert crypto.decrypt_or_plain(legacy) == legacy
    other_key = Fernet(Fernet.generate_key()).encrypt(b'x').decode()
    assert crypto.decrypt_or_plain(other_key) == other_key


def test_org_setting_password_encrypted_on_write(app, client, monkeypatch):
    """Saving org settings encrypts the SMTP password; reading it back decrypts."""
    from app.models import OrgSetting, User
    key = Fernet.generate_key()
    monkeypatch.setenv('SMTP_ENCRYPTION_KEY', key.decode())
    from app import db as sql_db, crypto
    with app.app_context():
        admin = User(username='rootadmin', email='rootadmin@example.com')
        admin.set_password('Str0ng!Passw0rd')
        admin.is_admin = True
        admin.is_staff = True
        sql_db.session.add(admin)
        sql_db.session.commit()
        OrgSetting.get()  # ensure the settings row exists
    client.post('/login', data={'username': 'rootadmin', 'password': 'Str0ng!Passw0rd'},
                environ_base={'REMOTE_ADDR': '203.0.113.30'})
    client.post('/admin/settings', data={
        'smtp_server': 'mail.example.com',
        'smtp_port': '587',
        'smtp_username': 'user',
        'smtp_password': 'SuperSecret123!',
        'smtp_from_email': 'noreply@example.com',
        'smtp_use_tls': True,
    }, follow_redirects=True)
    with app.app_context():
        stored = OrgSetting.get().smtp_password
        assert stored != 'SuperSecret123!'  # not stored in plaintext
        assert crypto.decrypt_or_plain(stored) == 'SuperSecret123!'


# ---------------------------------------------------------------------------
# S8 — self-registration gating
# ---------------------------------------------------------------------------

def test_registration_blocked_when_disabled(app, client, monkeypatch):
    monkeypatch.setenv('ALLOW_SELF_REGISTRATION', 'false')
    # The route flashes + redirects to /login rather than serving the form.
    r = client.get('/register', follow_redirects=True)
    assert r.status_code == 200
    assert b'registration is currently disabled' in r.data.lower()


def test_registration_enabled_by_default(app, client, monkeypatch):
    monkeypatch.delenv('ALLOW_SELF_REGISTRATION', raising=False)
    r = client.get('/register')
    assert r.status_code == 200  # form is served


# ---------------------------------------------------------------------------
# Q2 — Flask-Migrate schema bootstrap
# ---------------------------------------------------------------------------

HEAD_REVISION = 'b5b892f58eec'  # add case deleted_at soft-delete column (F5); keep in sync with migrations/versions/


def test_create_app_migrates_fresh_db(monkeypatch, tmp_path):
    """A brand-new DB is built entirely by the migrations (no create_all)."""
    from app import create_app, db
    from sqlalchemy import inspect, text
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path}/fresh.db')
    monkeypatch.setenv('SECRET_KEY', 'b' * 40)
    monkeypatch.setenv('ADMIN_CREATE', 'false')
    app = create_app(testing=True)
    with app.app_context():
        tables = inspect(db.engine).get_table_names()
        assert 'alembic_version' in tables
        assert 'audit_log' in tables
        version = db.session.execute(
            text('select version_num from alembic_version')
        ).scalar()
        assert version == HEAD_REVISION
        for name in ('user', 'case', 'group', 'org_setting', 'login_attempt', 'attachment'):
            assert name in tables, f'missing table {name}'


def test_initialize_database_stamps_legacy_db(app):
    """A pre-migration DB (tables exist, no alembic history) is aligned to head."""
    from app import _initialize_database, db
    from sqlalchemy import inspect, text
    with app.app_context():
        db.session.execute(text('DROP TABLE alembic_version'))
        db.session.commit()
        assert 'alembic_version' not in inspect(db.engine).get_table_names()
    _initialize_database(app)
    with app.app_context():
        assert db.session.execute(
            text('select version_num from alembic_version')
        ).scalar() == HEAD_REVISION
