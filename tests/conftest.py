"""Shared pytest fixtures for the Case-Tool test suite."""
import os
import tempfile

import pytest

os.environ['SECRET_KEY'] = 'test-secret-key'
os.environ['ADMIN_CREATE'] = 'false'

from app import create_app, db as sql_db  # noqa: E402


@pytest.fixture
def app(tmp_path):
    # isolate the DB before create_app reads DATABASE_URL at init time
    db_path = tmp_path / "test.db"
    os.environ['DATABASE_URL'] = f'sqlite:///{db_path}'
    application = create_app(testing=True)
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    # NOTE: schema is built by Flask-Migrate inside create_app() (Q2). We do not
    # call db.create_all() here so the suite exercises the real migration path.
    yield application
    try:
        os.remove(str(db_path))
    except OSError:
        pass


@pytest.fixture
def client(app):
    return app.test_client()


def _create_user(client, app, username, *, is_staff=False, is_admin=False,
                 password='Str0ng!Passw0rd', group=None):
    """Register + login a user via the real endpoints."""
    from app.models import User
    client.post('/register', data={
        'username': username,
        'email': f'{username}@example.com',
        'password': password,
    }, follow_redirects=True)
    with app.app_context():
        u = User.query.filter_by(username=username).first()
        u.is_staff = is_staff
        u.is_admin = is_admin
        if group is not None:
            u.groups.append(group)
        sql_db.session.commit()
    return client.post('/login', data={
        'username': username, 'password': password,
    }, follow_redirects=True)


@pytest.fixture
def staff_client(client, app):
    """A logged-in staff+admin user, plus a Triage group and default states/types."""
    from app.models import User, Group, CaseState, CaseType, CaseCategory
    with app.app_context():
        triage = Group(name='Triage')
        sql_db.session.add(triage)
        sql_db.session.commit()
        if not CaseState.query.filter_by(name='New').first():
            sql_db.session.add(CaseState(name='New', sort_order=0))
        ct = CaseType.query.filter_by(name='Technical').first()
        if ct is None:
            ct = CaseType(name='Technical', sort_order=0, sla_hours=48)
            sql_db.session.add(ct)
        ct.sla_hours = 48  # ensure SLA math has a real target
        sql_db.session.commit()
        username = 'staffadmin'
    _create_user(client, app, username, is_staff=True, is_admin=True, group=triage)
    return client


@pytest.fixture
def plain_client(client, app):
    """A logged-in non-staff end user."""
    from app.models import User
    with app.app_context():
        username = 'plainuser'
    _create_user(client, app, username, is_staff=False)
    return client
