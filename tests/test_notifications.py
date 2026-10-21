"""F7: in-app notifications center + unread badges.

Covers notification creation (assignment + SLA/OLA breach), the nav badge counts
exposed via the template context processor, the notifications center route, and
mark-as-read / mark-all-as-read actions.
"""
from datetime import datetime, timedelta


def _make_case(app, **overrides):
    from app import db as sql_db
    from app.models import Case, User, Group, CaseType, CaseCategory, CaseState
    with app.app_context():
        g = Group(name='Support7')
        sql_db.session.add(g)
        sql_db.session.commit()
        if not CaseType.query.filter_by(name='Technical').first():
            sql_db.session.add(CaseType(name='Technical', sla_hours=1))  # short target -> breaches fast
        if not CaseCategory.query.filter_by(name='Software').first():
            sql_db.session.add(CaseCategory(name='Software'))
        if not CaseState.query.filter_by(name='New').first():
            sql_db.session.add(CaseState(name='New', sort_order=0))
        u = User(username='staff7', email='s7@e.com')
        u.is_staff = True
        u.set_password('password1')
        g.users.append(u)
        sql_db.session.add(g)
        sql_db.session.commit()
        kwargs = {
            'title': 'C', 'description': 'd', 'user_id': u.id,
            'assignment_group_id': g.id, 'state_id': CaseState.query.filter_by(name='New').first().id,
            'case_type': 'Technical', 'category': 'Software', 'status': 'open',
        }
        kwargs.update(overrides)
        c = Case(**kwargs)
        sql_db.session.add(c)
        sql_db.session.commit()
        return c.id, u.id


def _seed_notification(app, user_id, event_type='assigned', case_id=None, read=False):
    from app import db as sql_db
    from app.models import Notification
    with app.app_context():
        sql_db.session.add(Notification(
            recipient_id=user_id, case_id=case_id, event_type=event_type,
            title=f'{event_type} test', body='x', is_read=read))
        sql_db.session.commit()


def test_assignment_creates_notification(app, staff_client):
    from app.models import Notification, Case
    cid, uid = _make_case(app, title='Assigned One')
    r = staff_client.post(
        f'/case/{cid}/assign',
        data={'assigned_to': uid},
        follow_redirects=True,
    )
    assert r.status_code == 200
    with app.app_context():
        notes = Notification.query.filter_by(recipient_id=uid, event_type='assigned').all()
        assert len(notes) == 1
        assert notes[0].case_id == cid
        assert notes[0].is_read is False


def test_sla_breach_creates_notification_for_assignee(app, monkeypatch):
    """Deterministic: force pct>=100 (red) so the breach path fires regardless
    of wall-clock/business-hours."""
    from app import db
    from app.models import Notification, Case
    from app.sla import update_sla
    monkeypatch.setattr('app.sla.get_sla_pct', lambda case: 100.0)

    cid, uid = _make_case(app, title='Will Breach')
    with app.app_context():
        c = Case.query.get(cid)
        c.assigned_to_id = uid
        db.session.commit()
        assert update_sla(c) == 'red'

    with app.app_context():
        notes = Notification.query.filter_by(recipient_id=uid, event_type='sla_breach').all()
        assert len(notes) == 1
        assert notes[0].case_id == cid


def test_nav_counts_exposed_to_templates(app, staff_client):
    """The nav badge counts are injected into every template via a context
    processor; asserting on rendered dashboard HTML proves they populate."""
    from app.models import User
    with app.app_context():
        u = User.query.filter_by(username='staffadmin').first()
        _seed_notification(app, u.id, event_type='assigned', read=False)

    r = staff_client.get('/dashboard')
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # Unread badge (count 1) and the notifications dropdown listing our title.
    assert 'badge badge-danger">1' in body
    assert 'assigned test' in body
    assert 'View all notifications' in body


def test_notifications_center_renders_and_lists(app, staff_client):
    from app.models import User
    with app.app_context():
        u = User.query.filter_by(username='staffadmin').first()
        _seed_notification(app, u.id, event_type='assigned', read=False)

    r = staff_client.get('/notifications')
    assert r.status_code == 200
    assert 'Notifications' in r.get_data(as_text=True)


def test_mark_notification_read(app, staff_client):
    from app.models import User, Notification
    with app.app_context():
        u = User.query.filter_by(username='staffadmin').first()
        _seed_notification(app, u.id)
        notif = Notification.query.filter_by(recipient_id=u.id, is_read=False).first()

    r = staff_client.post(f'/notifications/{notif.id}/read', follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        assert Notification.query.get(notif.id).is_read is True
        assert Notification.unread_count(u.id) == 0


def test_mark_all_read(app, staff_client):
    from app.models import User, Notification
    with app.app_context():
        u = User.query.filter_by(username='staffadmin').first()
        _seed_notification(app, u.id)
        _seed_notification(app, u.id)
        assert Notification.unread_count(u.id) == 2

    r = staff_client.post('/notifications/read-all', follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        assert Notification.unread_count(u.id) == 0


def test_unassigned_case_count_scopes_to_groups_and_excludes_resolved(app):
    from app.routes.cases import unassigned_case_count
    from app.models import Case, User
    cid, uid = _make_case(app, title='Unassigned Raw')
    with app.app_context():
        u = User.query.get(uid)
        # Already unassigned + open -> counts.
        assert unassigned_case_count(u) == 1
        # Resolve it -> no longer counted.
        Case.query.get(cid).status = 'resolved'
        db_session_commit(app)
        assert unassigned_case_count(u) == 0


def test_unassigned_case_count_zero_for_non_staff(app):
    from app.routes.cases import unassigned_case_count
    from app.models import User
    with app.app_context():
        owner = User.query.filter_by(is_staff=False).first()
        if owner is None:
            owner = User(username='enduser', email='e@e.com')
            owner.set_password('password1')
            db_session_commit(app)
        assert unassigned_case_count(owner) == 0


def test_non_staff_cannot_read_other_users_notification(app, plain_client):
    from app.models import User, Notification
    _, other_uid = _make_case(app, title='Private')
    with app.app_context():
        _seed_notification(app, other_uid, event_type='assigned')
        notif = Notification.query.filter_by(recipient_id=other_uid, is_read=False).first()
        reader = User.query.filter_by(is_staff=False).first()

    # plain_client is a different (non-staff) user -> denied, notification stays unread.
    r = plain_client.post(f'/notifications/{notif.id}/read', follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        assert Notification.query.get(notif.id).is_read is False


# --- helpers ---------------------------------------------------------------


def db_session_commit(app):
    from app import db as sql_db
    sql_db.session.commit()
