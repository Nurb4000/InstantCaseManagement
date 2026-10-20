"""Regression tests for CSV export, including cases with null group/state (B1)."""
import csv
import io


def _own_case(app, user_id, **overrides):
    from app import db as sql_db
    from app.models import Case
    with app.app_context():
        kwargs = {
            'title': 'Exported', 'description': 'd', 'user_id': user_id,
            'assignment_group_id': None, 'state_id': None,
            'assigned_to_id': None, 'status': 'open',
        }
        kwargs.update(overrides)
        c = Case(**kwargs)
        sql_db.session.add(c)
        sql_db.session.commit()
        return c.id


def test_export_user_csv_with_null_group_and_state(app, plain_client):
    from app.models import User
    with app.app_context():
        u = User.query.filter_by(username='plainuser').first()
        cid = _own_case(app, u.id)

    r = plain_client.get('/export/user')
    assert r.status_code == 200
    assert r.mimetype == 'text/csv'
    rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
    # header + the one case
    assert len(rows) == 2
    assert rows[1][0] == str(cid)


def test_export_all_csv_with_null_group_and_state(app, staff_client):
    from app import db as sql_db
    from app.models import Case, User
    with app.app_context():
        u = User.query.filter_by(username='staffadmin').first()
        cid = _own_case(app, u.id)
    r = staff_client.get('/export/all')
    assert r.status_code == 200
    rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
    assert len(rows) == 2


def test_export_assigned_csv_with_null_group_and_state(app, staff_client):
    # B1: a case with NULL group/state that is assigned to the current user must
    # still export cleanly (previously an unguarded relationship dereference
    # would raise AttributeError -> 500).
    from app import db as sql_db
    from app.models import Case, User
    with app.app_context():
        u = User.query.filter_by(username='staffadmin').first()
        cid = _own_case(app, u.id, assigned_to_id=u.id)
    r = staff_client.get('/export/assigned')
    assert r.status_code == 200
    rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
    assert len(rows) == 2
    # Group (col 6) and State (col 7) render empty for the null-group/state case.
    assert rows[1][6] == '' and rows[1][7] == ''
