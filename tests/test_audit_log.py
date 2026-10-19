"""F2: administrative audit trail tests.

Covers the ``log_audit`` helper, that each admin route records an entry, the
read-only audit-log view + CSV export, access control, and that secrets
(passwords) never leak into the log.
"""
from datetime import datetime


def _make_user(app, username, *, is_staff=False, is_admin=False):
    from app.models import User
    with app.app_context():
        from app import db as sql_db
        u = User(username=username, email=f'{username}@example.com')
        u.set_password('Str0ng!Passw0rd!')
        u.is_staff = is_staff
        u.is_admin = is_admin
        sql_db.session.add(u)
        sql_db.session.commit()
        return u.id


# ---------------------------------------------------------------------------
# helper
# ---------------------------------------------------------------------------

def test_log_audit_creates_row_with_actor(app):
    from app.audit import log_audit
    from app.models import AuditLog, User
    bob_id = _make_user(app, 'actorbob', is_staff=True, is_admin=True)
    with app.app_context():
        bob = User.query.get(bob_id)
        log_audit('user_create', target_type='User', target_id=7,
                  details='created bob', user=bob)
        row = AuditLog.query.order_by(AuditLog.id.desc()).first()
        assert row.action == 'user_create'
        assert row.target_type == 'User'
        assert row.target_id == 7
        assert row.actor_user_id == bob.id
        assert row.actor_name == 'actorbob'
        assert row.details == 'created bob'
        assert isinstance(row.timestamp, datetime)


def test_log_audit_never_raises_on_commit_failure(app):
    """A failing commit must be swallowed, not propagated to the caller."""
    from app.audit import log_audit
    from app import db as sql_db
    with app.app_context():
        orig_commit = sql_db.session.commit

        def boom(*a, **k):
            raise RuntimeError("simulated DB failure")

        sql_db.session.commit = boom
        try:
            # must not raise even though the commit fails
            log_audit('user_create', target_type='User', target_id=1, details='x')
        finally:
            sql_db.session.commit = orig_commit


def test_log_audit_outside_request_uses_anonymous(app):
    """Without a logged-in actor (and no explicit user) it still records a row."""
    from app.audit import log_audit
    from app.models import AuditLog
    with app.app_context():
        log_audit('system_action', target_type='OrgSetting', target_id=1, details='d')
        row = AuditLog.query.filter_by(action='system_action').first()
        assert row is not None
        assert row.actor_name is None


# ---------------------------------------------------------------------------
# route coverage
# ---------------------------------------------------------------------------

def test_create_user_is_logged(staff_client, app):
    _make_user(app, 'victim9')
    r = staff_client.post('/admin/users/create', data={
        'username': 'audituser', 'email': 'audituser@example.com',
        'password': 'Str0ng!Passw0rd!', 'confirm_password': 'Str0ng!Passw0rd!',
        'is_staff': False, 'is_admin': False,
    }, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        from app.models import AuditLog, User
        u = User.query.filter_by(username='audituser').first()
        entry = AuditLog.query.filter_by(action='user_create', target_id=u.id).first()
        assert entry is not None
        assert entry.actor_name == 'staffadmin'


def test_toggle_staff_is_logged(staff_client, app):
    target = _make_user(app, 'stafftogg', is_staff=False)
    r = staff_client.post(f'/admin/users/{target}/toggle-staff',
                          follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        from app.models import AuditLog
        entry = AuditLog.query.filter_by(action='user_toggle_staff', target_id=target).first()
        assert entry is not None
        assert 'stafftogg' in entry.details


def test_delete_group_is_logged(staff_client, app):
    from app.models import Group
    gid = _make_group(app, 'ToDelete')
    r = staff_client.post(f'/admin/groups/{gid}/delete', follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        from app.models import AuditLog
        entry = AuditLog.query.filter_by(action='group_delete', target_id=gid).first()
        assert entry is not None


def test_reset_password_does_not_log_secret(staff_client, app):
    target = _make_user(app, 'resetme', is_staff=True)
    r = staff_client.post(
        f'/admin/users/{target}/reset-password',
        data={'new_password': 'Str0ng!Passw0rd!', 'confirm_password': 'Str0ng!Passw0rd!'},
        follow_redirects=True,
    )
    assert r.status_code == 200
    with app.app_context():
        from app.models import AuditLog
        entry = AuditLog.query.filter_by(action='user_reset_password', target_id=target).first()
        assert entry is not None
        assert 'Str0ng!Passw0rd!' not in (entry.details or '')


def _make_group(app, name):
    from app.models import Group
    with app.app_context():
        from app import db as sql_db
        g = Group(name=name)
        sql_db.session.add(g)
        sql_db.session.commit()
        return g.id


# ---------------------------------------------------------------------------
# view + access control
# ---------------------------------------------------------------------------

def test_audit_log_view_visible_to_admin(staff_client, app):
    _make_user(app, 'logme', is_staff=True)
    staff_client.post('/admin/users/create', data={
        'username': 'logme2', 'email': 'logme2@example.com',
        'password': 'Str0ng!Passw0rd!', 'confirm_password': 'Str0ng!Passw0rd!',
    }, follow_redirects=True)
    r = staff_client.get('/admin/audit-log')
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'Audit Log' in body
    assert 'user_create' in body


def test_audit_log_view_denied_to_non_admin(plain_client, app):
    r = plain_client.get('/admin/audit-log')
    # admin_required redirects non-admins away (302)
    assert r.status_code == 302


def test_audit_log_filter_by_action(staff_client, app):
    _make_user(app, 'filterme', is_staff=True)
    staff_client.post('/admin/users/create', data={
        'username': 'filterme2', 'email': 'filterme2@example.com',
        'password': 'Str0ng!Passw0rd!', 'confirm_password': 'Str0ng!Passw0rd!',
    }, follow_redirects=True)
    r = staff_client.get('/admin/audit-log?action=user_create')
    assert r.status_code == 200
    assert 'user_create' in r.get_data(as_text=True)
    # a non-matching action filter yields no matching rows (still 200)
    r2 = staff_client.get('/admin/audit-log?action=group_delete')
    assert r2.status_code == 200


def test_export_audit_log_csv(staff_client, app):
    _make_user(app, 'csvme', is_staff=True)
    staff_client.post('/admin/users/create', data={
        'username': 'csvme2', 'email': 'csvme2@example.com',
        'password': 'Str0ng!Passw0rd!', 'confirm_password': 'Str0ng!Passw0rd!',
    }, follow_redirects=True)
    r = staff_client.get('/admin/audit-log/export')
    assert r.status_code == 200
    assert r.content_type == 'text/csv; charset=utf-8'
    text = r.get_data(as_text=True)
    assert 'timestamp,action,actor,target_type,target_id,details' in text
    assert 'user_create' in text
