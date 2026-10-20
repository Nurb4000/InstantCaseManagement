"""F3 regression: admin password reset forces a change on next login.

Covers the secure reset path (we never email a plaintext credential): an admin
reset marks the target user with ``force_password_reset``; their next login is
bounced to ``/change_password`` until they set a new password, at which point the
flag is cleared and normal access resumes.
"""
from app import db as sql_db
from app.models import User


def _make_user(app, username, *, is_staff=False, is_admin=False, password='Str0ng!Passw0rd'):
    from app.models import User
    with app.app_context():
        u = User(username=username, email=f'{username}@example.com')
        u.set_password(password)
        u.is_staff = is_staff
        u.is_admin = is_admin
        sql_db.session.add(u)
        sql_db.session.commit()
        return u.id


def test_admin_reset_forces_change_on_next_login(app):
    _make_user(app, 'resetadmin', is_staff=True, is_admin=True)
    victim_id = _make_user(app, 'victim')

    admin = app.test_client()
    victim = app.test_client()

    # --- Admin logs in and resets the victim's password --------------------
    admin.post('/login', data={'username': 'resetadmin', 'password': 'Str0ng!Passw0rd'},
               follow_redirects=True)
    r = admin.post(
        f'/admin/users/{victim_id}/reset-password',
        data={'new_password': 'Str0ng!NewPass1!', 'confirm_password': 'Str0ng!NewPass1!'},
        follow_redirects=True,
    )
    assert r.status_code == 200
    with app.app_context():
        assert User.query.get(victim_id).force_password_reset is True

    # --- Victim logs in; the forced-reset guard bounces them ---------------
    login = victim.post('/login',
                        data={'username': 'victim', 'password': 'Str0ng!NewPass1!'},
                        follow_redirects=False)
    assert login.status_code == 302
    assert login.headers['Location'].endswith('/dashboard')
    dash = victim.get('/dashboard')
    assert dash.status_code == 302
    assert dash.headers['Location'].endswith('/change_password')

    # --- Victim changes password; flag clears and access is restored -------
    change = victim.post(
        '/change_password',
        data={
            'current_password': 'Str0ng!NewPass1!',
            'new_password': 'Str0ng!Changed2!',
            'confirm_password': 'Str0ng!Changed2!',
        },
        follow_redirects=False,
    )
    assert change.status_code == 302
    with app.app_context():
        u = User.query.get(victim_id)
        assert u.force_password_reset is False
        assert u.check_password('Str0ng!Changed2!')
    assert victim.get('/dashboard').status_code == 200


def test_normal_login_not_redirected(app):
    """A user without a forced reset logs in and reaches the dashboard."""
    uid = _make_user(app, 'normaluser')
    c = app.test_client()
    login = c.post('/login',
                   data={'username': 'normaluser', 'password': 'Str0ng!Passw0rd'},
                   follow_redirects=False)
    assert login.status_code == 302
    assert login.headers['Location'].endswith('/dashboard')
    assert c.get('/dashboard').status_code == 200
