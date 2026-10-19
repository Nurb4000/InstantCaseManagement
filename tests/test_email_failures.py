"""Q6: email send failures must be surfaced to the acting user.

Previously callers ignored ``send_email``'s return value and always flashed
"sent", so an SMTP failure was only recorded in EmailLog. These tests force a
real (non-localhost) SMTP send to fail and assert the error is surfaced.
"""
import smtplib

from app.models import OrgSetting, Case, User


def _force_smtp_failure(app, monkeypatch):
    """Point OrgSetting at a non-localhost server and make SMTP connect blow up."""
    with app.app_context():
        from app import db as sql_db
        org = OrgSetting.get()
        org.smtp_server = 'mail.example.com'
        org.smtp_port = 587
        org.smtp_use_tls = False
        org.smtp_from_email = 'noreply@example.com'
        sql_db.session.commit()

    def _boom(*args, **kwargs):
        raise smtplib.SMTPConnectError(500, 'unreachable')

    monkeypatch.setattr(smtplib, 'SMTP', _boom)


def _make_owner(app, username):
    from app import db as sql_db
    with app.app_context():
        u = User(username=username, email=f'{username}@example.com')
        u.set_password('Str0ng!Passw0rd')
        sql_db.session.add(u)
        sql_db.session.commit()
        return u.id


def _make_case(app, *, title, user_id, assigned_to_id=None, group_id=1):
    from app import db as sql_db
    from app.models import Case
    with app.app_context():
        c = Case(title=title, description='d', user_id=user_id,
                 assigned_to_id=assigned_to_id, assignment_group_id=group_id,
                 status='open')
        sql_db.session.add(c)
        sql_db.session.commit()
        return c.id


def test_email_customer_surfaces_smtp_failure(app, staff_client, monkeypatch):
    _force_smtp_failure(app, monkeypatch)
    owner_id = _make_owner(app, 'owner_email')
    cid = _make_case(app, title='Email Me', user_id=owner_id)

    r = staff_client.post(f'/case/{cid}/email-customer',
                          data={'subject': 'Hi', 'body': 'There'},
                          follow_redirects=True)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'Email could not be sent' in body


def test_resolve_surfaces_smtp_failure(app, staff_client, monkeypatch):
    _force_smtp_failure(app, monkeypatch)
    owner_id = _make_owner(app, 'owner_resolve')
    with app.app_context():
        from app.models import User
        staffadmin = User.query.filter_by(username='staffadmin').first()
    cid = _make_case(app, title='Resolve Me', user_id=owner_id,
                     assigned_to_id=staffadmin.id)

    r = staff_client.post(f'/case/{cid}/resolve',
                          data={'resolve_reason': 'fixed it'},
                          follow_redirects=True)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # The action still succeeds; only the resolution email failed.
    assert 'Case resolved successfully' in body
    assert 'resolution email could not be sent' in body.lower()


def test_assign_surfaces_smtp_failure(app, staff_client, monkeypatch):
    _force_smtp_failure(app, monkeypatch)
    owner_id = _make_owner(app, 'owner_assign')
    with app.app_context():
        from app.models import User
        staffadmin = User.query.filter_by(username='staffadmin').first()
    cid = _make_case(app, title='Assign Me', user_id=owner_id)

    r = staff_client.post(f'/case/{cid}/assign',
                          data={'assigned_to': staffadmin.id},
                          follow_redirects=True)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'Case assigned successfully' in body
    assert 'assignment email could not be sent' in body.lower()


def test_smtp_happy_path_still_reports_sent(app, staff_client):
    """With the default localhost server, send_email short-circuits to success."""
    owner_id = _make_owner(app, 'owner_ok')
    cid = _make_case(app, title='Sent Me', user_id=owner_id)

    r = staff_client.post(f'/case/{cid}/email-customer',
                          data={'subject': 'Hi', 'body': 'There'},
                          follow_redirects=True)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'Email sent to' in body
    assert 'could not be sent' not in body.lower()
