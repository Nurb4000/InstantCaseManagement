"""Tests for Phase 2a security fixes: S1 (SECRET_KEY), S2 (admin bootstrap),
S3 (password policy), S7 (debug disabled)."""
import os

import pytest


# --- S1: SECRET_KEY enforcement -------------------------------------------------

def test_is_weak_secret_detects_placeholders_and_short_keys():
    from app import _is_weak_secret
    assert _is_weak_secret(None) is True
    assert _is_weak_secret('short') is True
    assert _is_weak_secret('generate-a-random-secret-key-here') is True
    assert _is_weak_secret('a' * 40) is False


def test_weak_secret_key_raises_outside_testing(monkeypatch):
    from app import create_app
    monkeypatch.setenv('SECRET_KEY', 'too-short')
    monkeypatch.setenv('ADMIN_CREATE', 'false')
    monkeypatch.delenv('SECRET_KEY_ALLOW_WEAK', raising=False)
    with pytest.raises(RuntimeError):
        create_app(testing=False)


def test_secret_key_allow_weak_flag(monkeypatch, tmp_path):
    from app import create_app
    db_path = tmp_path / 's1.db'
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{db_path}')
    monkeypatch.setenv('SECRET_KEY', 'too-short')
    monkeypatch.setenv('ADMIN_CREATE', 'false')
    monkeypatch.setenv('SECRET_KEY_ALLOW_WEAK', '1')
    app = create_app(testing=False)  # escape hatch lets local dev proceed without raising
    assert app.config['SECRET_KEY']


def test_testing_mode_allows_short_key():
    # S1 enforcement must not break the test suite (which uses short keys).
    from app import create_app
    app = create_app(testing=True)
    assert app.config['SECRET_KEY']


# --- S2: admin bootstrap --------------------------------------------------------

def _init_app(monkeypatch, tmp_path, admin_password):
    from app import create_app
    db_path = tmp_path / 's2.db'
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{db_path}')
    monkeypatch.setenv('ADMIN_CREATE', 'true')
    monkeypatch.setenv('ADMIN_PASSWORD', admin_password)
    monkeypatch.delenv('SECRET_KEY_ALLOW_WEAK', raising=False)
    return create_app(testing=True)


def test_admin_not_created_with_default_password(monkeypatch, tmp_path):
    from app.models import User
    app = _init_app(monkeypatch, tmp_path, 'changeme123')
    with app.app_context():
        admin = User.query.filter_by(username='admin').first()
    assert admin is None, "admin must NOT be created with a weak/default password"


def test_admin_not_created_when_unset(monkeypatch, tmp_path):
    from app.models import User
    monkeypatch.delenv('ADMIN_PASSWORD', raising=False)
    app = _init_app(monkeypatch, tmp_path, '')
    with app.app_context():
        admin = User.query.filter_by(username='admin').first()
    assert admin is None


def test_admin_created_with_strong_password(monkeypatch, tmp_path):
    from app.models import User
    pw = 'Str0ng!CaseAdmin_zxy'
    app = _init_app(monkeypatch, tmp_path, pw)
    with app.app_context():
        admin = User.query.filter_by(username='admin').first()
    assert admin is not None
    assert admin.is_admin and admin.is_staff
    assert admin.check_password(pw)


# --- S3: password policy --------------------------------------------------------

def test_password_strength_checker():
    from app.forms import _check_password_strength, password_is_strong
    assert _check_password_strength('password1') != []          # too short / no upper / no special
    assert _check_password_strength('changeme123') != []         # common
    assert _check_password_strength('Str0ng!Passw0rd') == []      # strong
    assert password_is_strong('Str0ng!Passw0rd') is True
    assert password_is_strong('changeme123') is False


def test_register_form_rejects_weak(app):
    from app.forms import RegisterForm
    with app.app_context():
        form = RegisterForm(data={
            'username': 'alice', 'email': 'alice@example.com', 'password': 'password1',
        })
        assert form.validate() is False


def test_register_form_rejects_common(app):
    from app.forms import RegisterForm
    with app.app_context():
        form = RegisterForm(data={
            'username': 'alice', 'email': 'alice@example.com', 'password': 'changeme123',
        })
        assert form.validate() is False


def test_register_form_accepts_strong(app):
    from app.forms import RegisterForm
    with app.app_context():
        form = RegisterForm(data={
            'username': 'alice', 'email': 'alice@example.com', 'password': 'Str0ng!Passw0rd',
        })
        assert form.validate() is True


# --- S7: debug disabled ---------------------------------------------------------

def test_debug_disabled_by_default(app):
    assert app.config.get('DEBUG') is False
