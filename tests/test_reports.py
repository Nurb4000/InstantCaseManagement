"""Tests for F1 reporting dashboard (app/routes/reports.py)."""
from datetime import datetime, timedelta

import pytest

from app import db as sql_db
from app.models import Case, Comment, SLAEvent, Group, CaseState, CaseType, User


def _make_case(app, *, title, user_id, group_id, status='open', case_type='Technical',
               category='Software', days_ago=0, resolved_days_ago=None,
               assigned_to_id=None, comment_days_ago=None, breached=False):
    created = datetime.utcnow() - timedelta(days=days_ago)
    c = Case(
        title=title, description='x', user_id=user_id,
        assignment_group_id=group_id, assigned_to_id=assigned_to_id,
        status=status, case_type=case_type, category=category,
        created_date=created,
        resolved_date=(datetime.utcnow() - timedelta(days=resolved_days_ago)) if resolved_days_ago else None,
    )
    sql_db.session.add(c)
    sql_db.session.commit()

    if comment_days_ago is not None:
        cm = Comment(content='first reply', user_id=user_id, case_id=c.id,
                     created_date=datetime.utcnow() - timedelta(days=comment_days_ago))
        sql_db.session.add(cm)
        sql_db.session.commit()

    if breached:
        ev = SLAEvent(case_id=c.id, event_type='sla_red',
                      timestamp=datetime.utcnow() - timedelta(days=days_ago))
        sql_db.session.add(ev)
        sql_db.session.commit()
    return c.id


@pytest.fixture
def seeded_client(staff_client, app):
    """Staff client pre-populated with a mix of cases for report assertions."""
    with app.app_context():
        triage = Group.query.filter_by(name='Triage').first()
        u = User.query.filter_by(username='staffadmin').first()
        # two open cases this month, one resolved compliant, one resolved breached
        _make_case(app, title='Open A', user_id=u.id, group_id=triage.id, days_ago=5,
                   comment_days_ago=2)
        _make_case(app, title='Open B', user_id=u.id, group_id=triage.id, days_ago=20)
        _make_case(app, title='Resolved Good', user_id=u.id, group_id=triage.id, status='resolved',
                   days_ago=40, resolved_days_ago=30, assigned_to_id=u.id,
                   comment_days_ago=38)
        _make_case(app, title='Resolved Bad', user_id=u.id, group_id=triage.id, status='resolved',
                   days_ago=50, resolved_days_ago=45, assigned_to_id=u.id, breached=True)
        # a case in a prior month to test monthly bucketing
        prior = datetime.utcnow() - timedelta(days=120)
        c = Case(title='Old', description='x', user_id=u.id, assignment_group_id=triage.id,
                 status='open', case_type='Technical', category='Software', created_date=prior)
        sql_db.session.add(c)
        sql_db.session.commit()
    return staff_client


def test_reports_requires_staff(app):
    c = app.test_client()
    c.post('/register', data={'username': 'plainuser', 'email': 'plainuser@example.com',
                              'password': 'Str0ng!Passw0rd'}, follow_redirects=True)
    c.post('/login', data={'username': 'plainuser', 'password': 'Str0ng!Passw0rd'},
           follow_redirects=True)
    r = c.get('/reports/')
    assert r.status_code == 302  # non-staff redirected away (access denied)


def test_reports_dashboard_counts(seeded_client):
    r = seeded_client.get('/reports/')
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # 5 total cases seeded (Open A, Open B, Resolved Good, Resolved Bad, Old)
    assert 'Total Cases' in body


def test_sla_computation(seeded_client, app):
    from app.routes.reports import _report_data
    with app.app_context():
        from app.routes.cases import _date_filter
        cases = _date_filter(Case.query, '', '').all()
        data = _report_data(cases, 'monthly')
    assert data['total'] == 5
    assert data['resolved'] == 2
    assert data['open'] == 3
    # 2 resolved cases have an SLA target (Technical=48h); one breached -> 50% compliance
    assert data['compliant_total'] == 2
    assert data['compliant_ok'] == 1
    assert data['breached_count'] == 1
    assert data['compliance_rate'] == pytest.approx(50.0)


def test_first_response_and_resolution(seeded_client, app):
    from app.routes.reports import _report_data
    with app.app_context():
        from app.routes.cases import _date_filter
        cases = _date_filter(Case.query, '', '').all()
        data = _report_data(cases, 'monthly')
    # only 2 cases have comments -> first-response average is defined
    assert data['avg_response'] is not None and data['avg_response'] >= 0
    # 2 resolved cases with both created and resolved dates -> resolution defined
    assert data['avg_resolve'] is not None and data['avg_resolve'] > 0


def test_volume_monthly_bucketing(seeded_client, app):
    from app.routes.reports import _volume_series
    with app.app_context():
        from app.routes.cases import _date_filter
        cases = _date_filter(Case.query, '', '').all()
        series = _volume_series(cases, 'monthly')
    labels = {row['label'] for row in series}
    # 120 days ago lands in an earlier month than the last 60 days
    assert len(labels) >= 2


def test_export_csv(seeded_client):
    r = seeded_client.get('/reports/export')
    assert r.status_code == 200
    assert r.content_type.startswith('text/csv')
    body = r.get_data(as_text=True)
    assert 'SLA compliance rate' in body
    assert 'Total cases' in body


def test_date_filter_scopes_report(seeded_client, app):
    from app.routes.reports import _report_data
    # restrict to the last 10 days: only Open A qualifies (days_ago=5)
    with app.app_context():
        from app.routes.cases import _date_filter
        cases = _date_filter(Case.query, (datetime.utcnow() - timedelta(days=10)).strftime('%Y-%m-%d'),
                             datetime.utcnow().strftime('%Y-%m-%d')).all()
        data = _report_data(cases, 'daily')
    assert data['total'] == 1
