"""Regression test for dashboard OLA/SLA status persistence (B3)."""
from datetime import datetime, timedelta

from app.models import Case, Group


def _unassigned_active_case(app, group_id, user_id):
    from app import db as sql_db
    with app.app_context():
        c = Case(
            title='Active', description='d', user_id=user_id,
            assignment_group_id=group_id, assigned_to_id=None, status='open',
            case_type='Technical', category='Software',
            ola_started_at=datetime.utcnow() - timedelta(hours=3),
            sla_started_at=datetime.utcnow() - timedelta(hours=3),
        )
        sql_db.session.add(c)
        sql_db.session.commit()
        return c.id


def test_dashboard_persists_ola_sla_status(staff_client, app):
    from app.models import Group as G
    with app.app_context():
        triage = G.query.filter_by(name='Triage').first()
        from app.models import User
        u = User.query.filter_by(username='staffadmin').first()
        cid = _unassigned_active_case(app, triage.id, u.id)

    # Hit the staff dashboard (runs update_ola/update_sla per case)
    r = staff_client.get('/dashboard')
    assert r.status_code == 200

    # In a fresh session the computed statuses must have been committed.
    with app.app_context():
        c = Case.query.get(cid)
        assert c.ola_status is not None, "OLA status not persisted after dashboard"
        assert c.sla_status is not None, "SLA status not persisted after dashboard"
