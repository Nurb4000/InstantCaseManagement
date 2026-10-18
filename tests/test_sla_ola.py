"""Tests for SLA/OLA business-hours math and the stuck-pause recovery (B4)."""
from datetime import datetime, timedelta

from app.models import Case, User, Group, CaseState, CaseType, CaseCategory


def _make_case(app, **overrides):
    from app import db as sql_db
    with app.app_context():
        g = Group(name='Support')
        sql_db.session.add(g)
        sql_db.session.commit()
        if not CaseType.query.filter_by(name='Technical').first():
            sql_db.session.add(CaseType(name='Technical', sla_hours=48))
        if not CaseCategory.query.filter_by(name='Software').first():
            sql_db.session.add(CaseCategory(name='Software'))
        if not CaseState.query.filter_by(name='New').first():
            sql_db.session.add(CaseState(name='New', sort_order=0))
        sql_db.session.commit()
        u = User(username='a', email='a@e.com')
        u.set_password('password1')
        sql_db.session.add(u)
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
        cid = c.id
    return cid


def test_business_hours_simple(app):
    from app.sla import get_org_business_hours_elapsed
    start = datetime(2026, 6, 29, 9, 0, 0)   # Monday 09:00
    end = datetime(2026, 6, 29, 15, 0, 0)    # Monday 15:00
    with app.app_context():
        # org business hours 09:00-17:00 -> 6h counted
        assert get_org_business_hours_elapsed(start, end) == 6.0


def test_business_hours_outside_window(app):
    from app.sla import get_org_business_hours_elapsed
    start = datetime(2026, 6, 29, 20, 0, 0)  # after 17:00 close
    end = datetime(2026, 6, 29, 22, 0, 0)
    with app.app_context():
        assert get_org_business_hours_elapsed(start, end) == 0.0


def test_sla_pct_none_without_target(app):
    cid = _make_case(app, case_type='Nonexistent')
    with app.app_context():
        from app.sla import get_sla_pct
        c = Case.query.get(cid)
        assert get_sla_pct(c) is None


def test_sla_resumed_event_logged(app):
    from app import db as sql_db
    from app.models import SLAEvent
    from app.sla import pause_sla, resume_sla
    cid = _make_case(app)
    with app.app_context():
        c = Case.query.get(cid)
        c.sla_started_at = datetime.utcnow() - timedelta(hours=2)
        sql_db.session.commit()
        pause_sla(c)
        assert c.sla_paused_at is not None
        resume_sla(c)
        assert c.sla_paused_at is None
        events = SLAEvent.query.filter_by(case_id=cid).all()
        assert any(e.event_type == 'sla_resumed' for e in events)


def test_stuck_pause_auto_resume(app, monkeypatch):
    """B4: a pause open longer than the safety valve is auto-resumed."""
    from app import db as sql_db
    from app.sla import update_sla, STUCK_SLA_PAUSE_HOURS
    from app.models import SLAEvent
    # shrink the threshold so the test is fast/deterministic
    monkeypatch.setattr('app.sla.STUCK_SLA_PAUSE_HOURS', 1.0)
    cid = _make_case(app)
    with app.app_context():
        c = Case.query.get(cid)
        base = datetime.utcnow() - timedelta(hours=10)
        c.sla_started_at = base
        c.sla_paused_at = base - timedelta(hours=100)  # open far beyond 1h valve
        sql_db.session.commit()

        color = update_sla(c)  # should auto-resume the stuck pause

        c = Case.query.get(cid)
        assert c.sla_paused_at is None, "stuck pause should have been resumed"
        events = SLAEvent.query.filter_by(case_id=cid, event_type='sla_resumed').all()
        assert events and 'auto-resumed' in (events[-1].details or '')
