"""Tests for F5 (soft-delete + retention) and F9 (bulk actions + CSV import)."""
import csv
import io
from datetime import datetime, timedelta


def _get_group_id(app, name):
    from app.models import Group
    with app.app_context():
        g = Group.query.filter_by(name=name).first()
        if not g:
            g = Group(name=name)
            from app import db as sql_db
            sql_db.session.add(g)
            sql_db.session.commit()
        return g.id


def _create_user(app, username, *, is_staff=False, is_admin=False, groups=None):
    """Create a user (by name) and return its id. ``groups`` is a list of names."""
    from app.models import User, Group
    with app.app_context():
        u = User(username=username, email=f'{username}@example.com')
        u.set_password('Str0ng!Passw0rd!')
        u.is_staff = is_staff
        u.is_admin = is_admin
        for name in (groups or []):
            g = Group.query.filter_by(name=name).first()
            if g and g not in u.groups:
                u.groups.append(g)
        from app import db as sql_db
        sql_db.session.add(u)
        sql_db.session.commit()
        return u.id


def _make_case(app, *, title, user_id, group_id=None, status='open',
               case_type='Technical', assigned_to_id=None, deleted_days_ago=None):
    from app import db as sql_db
    from app.models import Case
    with app.app_context():
        kwargs = dict(title=title, description='d', user_id=user_id,
                      assignment_group_id=group_id, state_id=None,
                      assigned_to_id=assigned_to_id, status=status,
                      case_type=case_type, category='Software')
        if deleted_days_ago is not None:
            kwargs['deleted_at'] = datetime.utcnow() - timedelta(days=deleted_days_ago)
        c = Case(**kwargs)
        sql_db.session.add(c)
        sql_db.session.commit()
        return c.id


def _upload(csv_rows):
    text = io.StringIO()
    w = csv.writer(text)
    for r in csv_rows:
        w.writerow(r)
    return io.BytesIO(text.getvalue().encode('utf-8'))


def _register_client(app, username, password='Str0ng!Passw0rd!'):
    """Log in an existing user and return the client."""
    c = app.test_client()
    c.post('/login', data={'username': username, 'password': password},
           follow_redirects=True)
    return c


# ---------------------------------------------------------------------------
# F5 — soft delete + retention
# ---------------------------------------------------------------------------

def test_bulk_delete_hides_case(staff_client, app):
    from app.models import User, Case
    with app.app_context():
        u = User.query.filter_by(username='staffadmin').first()
        triage = _get_group_id(app, 'Triage')
        cid = _make_case(app, title='Delete Me', user_id=u.id, group_id=triage)

    r = staff_client.post('/bulk-action', data={'case_ids': [cid], 'action': 'delete'})
    assert r.status_code == 302
    with app.app_context():
        case = Case.query.get(cid)
        assert case.deleted_at is not None
        titles = [c.title for c in Case.query.filter(Case.deleted_at.is_(None)).all()]
    assert 'Delete Me' not in titles


def test_restore_case(staff_client, app):
    from app.models import User, Case
    with app.app_context():
        u = User.query.filter_by(username='staffadmin').first()
        triage = _get_group_id(app, 'Triage')
        cid = _make_case(app, title='Restore Me', user_id=u.id, group_id=triage)
    staff_client.post('/bulk-action', data={'case_ids': [cid], 'action': 'delete'})
    r = staff_client.post(f'/case/{cid}/restore')
    assert r.status_code == 302
    with app.app_context():
        assert Case.query.get(cid).deleted_at is None


def test_deleted_case_cannot_be_viewed(staff_client, app):
    from app.models import User, Case
    with app.app_context():
        u = User.query.filter_by(username='staffadmin').first()
        triage = _get_group_id(app, 'Triage')
        cid = _make_case(app, title='Gone', user_id=u.id, group_id=triage)
    staff_client.post('/bulk-action', data={'case_ids': [cid], 'action': 'delete'})
    r = staff_client.get(f'/case/{cid}')
    assert r.status_code == 404


def test_purge_hard_deletes_expired(app):
    from app.models import Case
    triage = _get_group_id(app, 'Triage')
    uid = _create_user(app, 'purgeuser', is_staff=True, groups=['Triage'])
    old = _make_case(app, title='Old', user_id=uid, group_id=triage, deleted_days_ago=400)
    recent = _make_case(app, title='Recent', user_id=uid, group_id=triage, deleted_days_ago=10)

    from app.routes.cases import purge_expired_cases
    with app.app_context():
        kept = purge_expired_cases(retention_days=365, actor_name='test')

    assert kept == 1
    with app.app_context():
        assert Case.query.get(old) is None          # hard-deleted past window
        assert Case.query.get(recent) is not None   # within window, retained


def test_purge_disabled_when_zero(app):
    from app.models import Case
    triage = _get_group_id(app, 'Triage')
    uid = _create_user(app, 'nopurgeuser', is_staff=True, groups=['Triage'])
    _make_case(app, title='Ancient', user_id=uid, group_id=triage, deleted_days_ago=9999)

    from app.routes.cases import purge_expired_cases
    with app.app_context():
        assert purge_expired_cases(retention_days=0) == 0
    with app.app_context():
        assert Case.query.filter(Case.deleted_at.isnot(None)).count() == 1


def test_purge_route_requires_admin(app, plain_client):
    r = plain_client.post('/admin/cases/purge')
    assert r.status_code == 302  # redirected away (not admin)


# ---------------------------------------------------------------------------
# F9 — bulk actions authorization
# ---------------------------------------------------------------------------

def test_bulk_state_change_scoped_to_groups(app):
    from app.models import Case
    own = _get_group_id(app, 'OwnGroup')
    other = _get_group_id(app, 'OtherGroup')
    uid = _create_user(app, 'staffscoped', is_staff=True, groups=['OwnGroup'])
    with app.app_context():
        from app.models import CaseState
        state = CaseState.query.filter_by(name='In Progress').first()

    in_own = _make_case(app, title='Own Case', user_id=uid, group_id=own)
    in_other = _make_case(app, title='Other Case', user_id=uid, group_id=other)

    staff = _register_client(app, 'staffscoped')
    staff.post('/bulk-action', data={
        'case_ids': [in_own, in_other], 'action': 'change_state',
        'state_id': state.id, 'reason': 'triage',
    })
    with app.app_context():
        own_case = Case.query.get(in_own)
        other_case = Case.query.get(in_other)
    assert own_case.state_id == state.id          # acted on (staff's group)
    assert other_case.state_id is None            # skipped (not staff's group)


def test_bulk_resolve_only_assigned(app):
    from app.models import Case
    triage = _get_group_id(app, 'Triage')
    uid = _create_user(app, 'resolver', is_staff=True, groups=['Triage'])
    assigned = _make_case(app, title='Mine', user_id=uid, group_id=triage,
                          assigned_to_id=uid, status='open')
    unassigned = _make_case(app, title='Not Mine', user_id=uid, group_id=triage,
                            assigned_to_id=None, status='open')

    staff = _register_client(app, 'resolver')
    staff.post('/bulk-action', data={
        'case_ids': [assigned, unassigned], 'action': 'resolve', 'reason': 'fixed',
    })
    with app.app_context():
        assert Case.query.get(assigned).status == 'resolved'
        assert Case.query.get(unassigned).status == 'open'  # not assigned to them


def test_bulk_assign_requires_shared_group(app):
    from app.models import Case
    triage = _get_group_id(app, 'Triage')
    alt = _get_group_id(app, 'AltGroup')
    staff_uid = _create_user(app, 'bulkstaff', is_staff=True, groups=['Triage'])
    assignee_uid = _create_user(app, 'assignee', is_staff=True, groups=['AltGroup'])

    cid = _make_case(app, title='Loose', user_id=staff_uid, group_id=triage, status='open')
    staff = _register_client(app, 'bulkstaff')
    r = staff.post('/bulk-action', data={
        'case_ids': [cid], 'action': 'assign', 'assigned_to': assignee_uid,
    })
    assert r.status_code == 302
    with app.app_context():
        assert Case.query.get(cid).assigned_to_id is None


# ---------------------------------------------------------------------------
# F9 — CSV import
# ---------------------------------------------------------------------------

def test_import_cases(staff_client, app):
    from app.models import User, Case
    with app.app_context():
        u = User.query.filter_by(username='staffadmin').first()

    csv_data = _upload([
        ['Title', 'Description', 'Submitted By', 'Type', 'Category', 'Group', 'Status'],
        ['Imported One', 'desc one', 'staffadmin', 'Technical', 'Software', 'Triage', 'open'],
        ['Imported Two', 'desc two', 'staffadmin', 'Billing', 'Hardware', 'Triage', 'in progress'],
    ])
    r = staff_client.post(
        '/admin/cases/import',
        data={'file': (csv_data, 'import.csv')},
        content_type='multipart/form-data',
    )
    assert r.status_code == 302
    with app.app_context():
        one = Case.query.filter_by(title='Imported One').first()
        two = Case.query.filter_by(title='Imported Two').first()
    assert one is not None and one.user_id == u.id
    assert one.case_type == 'Technical' and one.status == 'open'
    assert two is not None and two.status == 'in progress'
    assert one.sla_started_at is not None  # SLA started (Technical has a target)


def test_import_requires_admin(app, plain_client):
    csv_data = _upload([['Title', 'Description'], ['X', 'Y']])
    r = plain_client.post(
        '/admin/cases/import',
        data={'file': (csv_data, 'import.csv')},
        content_type='multipart/form-data',
    )
    assert r.status_code == 302


def test_import_skips_missing_submitter(staff_client, app):
    from app.models import Case
    csv_data = _upload([
        ['Title', 'Description', 'Submitted By'],
        ['Good', 'ok', 'staffadmin'],
        ['Bad', 'no such user', 'ghostuser'],
    ])
    staff_client.post(
        '/admin/cases/import',
        data={'file': (csv_data, 'import.csv')},
        content_type='multipart/form-data',
    )
    with app.app_context():
        assert Case.query.filter_by(title='Good').first() is not None
        assert Case.query.filter_by(title='Bad').first() is None


def test_import_get_shows_form(staff_client):
    r = staff_client.get('/admin/cases/import')
    assert r.status_code == 200
    assert 'Import Cases' in r.get_data(as_text=True)


def test_all_cases_page_renders_bulk_form(staff_client, app):
    from app.models import User, Case
    with app.app_context():
        u = User.query.filter_by(username='staffadmin').first()
        triage = _get_group_id(app, 'Triage')
        _make_case(app, title='Bulk Me', user_id=u.id, group_id=triage)
    r = staff_client.get('/cases')
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'Bulk actions' in body
    assert 'name="case_ids"' in body            # per-row checkboxes
    assert 'name="action"' in body              # action selector


def test_deleted_cases_page_renders(staff_client, app):
    from app.models import User, Case
    with app.app_context():
        u = User.query.filter_by(username='staffadmin').first()
        triage = _get_group_id(app, 'Triage')
        cid = _make_case(app, title='For Delete', user_id=u.id, group_id=triage)
    staff_client.post('/bulk-action', data={'case_ids': [cid], 'action': 'delete'})
    r = staff_client.get('/admin/cases/deleted')
    assert r.status_code == 200
    assert 'Deleted Cases' in r.get_data(as_text=True)
