"""Q7: shared escalation catch-up logging (app/escalation.py).

Unit tests lock the control-flow contract of ``log_threshold_catchup``; the
SLA/OLA integration tests lock that update_sla/update_ola still backfill the
missing yellow/orange/red milestones exactly once and idempotently.
"""
from datetime import datetime, timedelta
from collections import Counter


def test_catchup_logs_missing_levels_in_ascending_order():
    from app.escalation import log_threshold_catchup
    state = {'orange': True}  # orange already logged for this case
    seen = []

    def has_event(key):
        return key in state

    def log_and_notify(key):
        state[key] = True
        seen.append(key)

    log_threshold_catchup(('yellow', 'orange', 'red'), 'red', has_event, log_and_notify)
    # orange skipped (exists); yellow and red backfilled, ascending.
    assert seen == ['yellow', 'red']


def test_catchup_yellow_only_logs_yellow():
    from app.escalation import log_threshold_catchup
    seen = []
    log_threshold_catchup(('yellow', 'orange', 'red'), 'yellow',
                          lambda k: False, lambda k: seen.append(k))
    assert seen == ['yellow']


def test_catchup_green_and_unknown_levels_are_noop():
    from app.escalation import log_threshold_catchup
    called = []
    for current in ('green', None, 'purple'):
        log_threshold_catchup(('yellow', 'orange', 'red'), current,
                              lambda k: False, lambda k: called.append(k))
    assert called == []


def _seed_case(app, *, sla_started_ago=None, ola_started_ago=None):
    """Create a case wired to a fresh group + a fast-firing SLA type.

    Reuses the pre-seeded 'New' state and 'Software' category; creates its own
    group/type/user with unique names to avoid collisions.
    """
    from app import db as sql_db
    from app.models import Case, User, Group, CaseType, CaseState
    with app.app_context():
        g = Group(name='GroupQ7')
        ct = CaseType(name='SlaOlaTest', sla_hours=1)  # 1h target -> red fast
        st = CaseState.query.filter_by(name='New').first()
        u = User(username='qa7', email='qa7@example.com')
        u.set_password('password1')
        for obj in (g, ct, u):
            sql_db.session.add(obj)
        sql_db.session.commit()

        c = Case(title='t', description='d', user_id=u.id,
                 assignment_group_id=g.id, state_id=st.id,
                 case_type='SlaOlaTest', category='Software', status='open',
                 assigned_to_id=None)
        if sla_started_ago is not None:
            c.sla_started_at = datetime.utcnow() - sla_started_ago
        if ola_started_ago is not None:
            c.ola_started_at = datetime.utcnow() - ola_started_ago
        sql_db.session.add(c)
        sql_db.session.commit()
        return c.id


def test_sla_red_backfills_missing_milestones(app):
    from app import db as sql_db
    from app.models import Case, SLAEvent
    from app.sla import update_sla
    cid = _seed_case(app, sla_started_ago=timedelta(days=30))

    with app.app_context():
        color = update_sla(Case.query.get(cid))

    assert color == 'red'
    with app.app_context():
        types = sorted(e.event_type for e in SLAEvent.query.filter_by(case_id=cid).all())
    assert types == ['sla_orange', 'sla_red', 'sla_yellow']


def test_sla_catchup_is_idempotent(app):
    from app import db as sql_db
    from app.models import Case, SLAEvent
    from app.sla import update_sla
    cid = _seed_case(app, sla_started_ago=timedelta(days=30))

    with app.app_context():
        c = Case.query.get(cid)
        update_sla(c)
        update_sla(c)

    with app.app_context():
        counter = Counter(e.event_type for e in SLAEvent.query.filter_by(case_id=cid).all())
    assert counter == {'sla_yellow': 1, 'sla_orange': 1, 'sla_red': 1}


def test_ola_red_backfills_missing_milestones(app):
    from app import db as sql_db
    from app.models import Case, OLAEvent
    from app.ola import update_ola
    cid = _seed_case(app, ola_started_ago=timedelta(days=30))

    with app.app_context():
        color = update_ola(Case.query.get(cid))

    assert color == 'red'
    with app.app_context():
        types = sorted(e.event_type for e in OLAEvent.query.filter_by(case_id=cid).all())
    assert types == ['ola_orange', 'ola_red', 'ola_yellow']
