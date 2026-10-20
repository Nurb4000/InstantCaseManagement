"""F4 regression: case priority (P1-P5) triage field.

Covers persistence through submit (default + explicit), editing, and the
staff all-cases triage sort (highest priority first, recency within a level).
"""
from datetime import datetime, timedelta

from app.models import Case


def _make_case(app, *, title, priority, created_days_ago=0, user=None, is_staff_owner=False):
    from app.models import User
    with app.app_context():
        if user is None:
            user = User.query.filter_by(username='staffadmin').first()
        created = datetime.utcnow() - timedelta(days=created_days_ago)
        c = Case(
            title=title, description='d', user_id=user.id,
            case_type='Technical', category='Software',
            priority=priority, created_date=created, status='open',
        )
        from app import db as sql_db
        sql_db.session.add(c)
        sql_db.session.commit()
        return c.id


def test_staff_submit_sets_priority(staff_client, app):
    r = staff_client.post('/submit_case', data={
        'title': 'Priority case', 'description': 'desc',
        'case_type': 'Technical', 'category': 'Software',
        'priority': 'P1', 'submitted_for': 'Acme',
    }, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        c = Case.query.filter_by(title='Priority case').first()
        assert c.priority == 'P1'
        assert c.priority_label == 'Highest'


def test_nonstaff_submit_defaults_to_p3(plain_client, app):
    r = plain_client.post('/submit_case', data={
        'title': 'Default prio', 'description': 'desc',
        'case_type': 'Technical', 'category': 'Software',
        'submitted_for': 'Acme',
    }, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        c = Case.query.filter_by(title='Default prio').first()
        assert c.priority == Case.PRIORITY_DEFAULT == 'P3'


def test_edit_updates_and_ignores_empty_priority(staff_client, app):
    cid = _make_case(app, title='Editable', priority='P4', created_days_ago=2)

    # Set a new valid priority.
    staff_client.post(f'/case/{cid}/edit', data={
        'title': 'Editable', 'description': 'desc',
        'case_type': 'Technical', 'category': 'Software',
        'priority': 'P1',
    }, follow_redirects=True)
    with app.app_context():
        assert Case.query.get(cid).priority == 'P1'

    # Submitting an empty priority leaves the existing value untouched.
    staff_client.post(f'/case/{cid}/edit', data={
        'title': 'Editable', 'description': 'desc',
        'case_type': 'Technical', 'category': 'Software',
        'priority': '',
    }, follow_redirects=True)
    with app.app_context():
        assert Case.query.get(cid).priority == 'P1'


def test_all_cases_sorted_by_priority_first(staff_client, app):
    p5 = _make_case(app, title='P5 case', priority='P5', created_days_ago=5)
    p1_old = _make_case(app, title='P1 old', priority='P1', created_days_ago=4)
    p1_new = _make_case(app, title='P1 new', priority='P1', created_days_ago=1)
    p3 = _make_case(app, title='P3 case', priority='P3', created_days_ago=3)

    r = staff_client.get('/cases')
    assert r.status_code == 200
    body = r.data.decode()
    # Highest priority first; within P1 the more recent case precedes the older.
    positions = {t: body.index(t) for t in ('P1 new', 'P1 old', 'P3 case', 'P5 case')}
    assert list(positions.values()) == sorted(positions.values()), positions
    assert positions['P1 new'] < positions['P1 old']
