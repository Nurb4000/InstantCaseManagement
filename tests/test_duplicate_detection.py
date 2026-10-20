"""F6: near-duplicate case detection on submit and import paths.

Verifies that a second (near-identical) case is blocked at submit time with an
actionable message, that genuinely distinct cases still create, and that the
import path skips duplicate rows (both duplicates of existing cases and rows that
duplicate earlier rows within the same import). Soft-deleted cases are ignored,
so F6 does not interfere with F5 archival.
"""
import csv
import io
from datetime import datetime, timedelta


def _upload(csv_rows):
    text = io.StringIO()
    w = csv.writer(text)
    for r in csv_rows:
        w.writerow(r)
    return io.BytesIO(text.getvalue().encode('utf-8'))


def _seed_reference_data(app):
    """Ensure a CaseType and CaseCategory exist so submit form choices validate."""
    from app import db as sql_db
    from app.models import CaseType, CaseCategory
    with app.app_context():
        if not CaseType.query.filter_by(name='Technical').first():
            sql_db.session.add(CaseType(name='Technical', sort_order=0, sla_hours=48))
        if not CaseCategory.query.filter_by(name='Software').first():
            sql_db.session.add(CaseCategory(name='Software', sort_order=0))
        sql_db.session.commit()


def _make_case(app, title, description, *, username='staffadmin', **extra):
    from app import db as sql_db
    from app.models import Case, User
    with app.app_context():
        u = User.query.filter_by(username=username).first()
        c = Case(title=title, description=description, user_id=u.id,
                 case_type='Technical', category='Software', status='open', **extra)
        sql_db.session.add(c)
        sql_db.session.commit()
        return c


def _submit(client, title, description):
    return client.post('/submit_case', data={
        'title': title,
        'description': description,
        'case_type': 'Technical',
        'category': 'Software',
        'submitted_for': 'Acme',
    }, follow_redirects=True)


def _count(app, title):
    from app.models import Case
    with app.app_context():
        return Case.query.filter_by(title=title).count()


# --- submit path -----------------------------------------------------------


def test_submit_blocks_exact_duplicate(staff_client, app):
    _seed_reference_data(app)
    _make_case(app, 'Printer not printing', "The office printer won't print anything.")
    before = _count(app, 'Printer not printing')

    r = _submit(staff_client, 'Printer not printing', "The office printer won't print anything.")
    assert r.status_code == 200
    # No second row created; user is told an identical case already exists.
    assert _count(app, 'Printer not printing') == before
    assert b'already exists' in r.data.lower()


def test_submit_blocks_near_duplicate_title(staff_client, app):
    _seed_reference_data(app)
    _make_case(app, 'My laptop will not turn on', 'Black screen, no lights at all.')

    # Intra-word typo keeps the same words (high token overlap) but is clearly
    # the same request.
    r = _submit(staff_client, 'My laptop willl not turn on',
               'A completely unrelated description about a different topic entirely.')
    assert r.status_code == 200
    # Near-identical title is blocked...
    assert _count(app, 'My laptop willl not turn on') == 0
    # ...and the original is left untouched.
    assert _count(app, 'My laptop will not turn on') == 1


def test_submit_allows_shared_prefix_distinct_titles(staff_client, app):
    """Titles that share a long prefix but differ in a token are NOT duplicates."""
    _seed_reference_data(app)
    _make_case(app, 'Imported One', 'First import batch.')

    r = _submit(staff_client, 'Imported Two', 'A genuinely second, distinct request.')
    assert r.status_code == 200
    assert _count(app, 'Imported Two') == 1


def test_submit_allows_distinct_case(staff_client, app):
    _seed_reference_data(app)
    _make_case(app, 'WiFi cannot connect', 'Cannot authenticate to corporate VPN.')

    r = _submit(staff_client, 'New request: ergonomic keyboard',
               'I would like an ergonomic keyboard for my desk.')
    assert r.status_code == 200
    c = _count(app, 'New request: ergonomic keyboard')
    assert c == 1
    # F4 default still applies when priority not chosen.
    from app.models import Case
    with app.app_context():
        assert Case.query.filter_by(title='New request: ergonomic keyboard').first().priority == 'P3'


def test_submit_duplicate_blocked_for_non_staff(plain_client, app):
    _seed_reference_data(app)
    _make_case(app, 'Badge reader down', 'Access badge no longer opens the lobby door.',
               username='plainuser')

    r = _submit(plain_client, 'Badge reader down', 'Access badge no longer works.')
    assert r.status_code == 200
    assert _count(app, 'Badge reader down') == 1  # not duplicated

    # A distinct case by the same non-staff user is allowed.
    r2 = _submit(plain_client, 'Parking gate stuck', 'The car gate is jammed open.')
    assert r2.status_code == 200
    assert _count(app, 'Parking gate stuck') == 1


# --- import path -----------------------------------------------------------


def test_import_skips_duplicate_of_existing(staff_client, app):
    _make_case(app, 'Existing ticket', 'Original description of the issue.')
    csv_data = _upload([
        ['Title', 'Description', 'Submitted By', 'Type', 'Category', 'Group', 'Status'],
        ['Existing ticket', 'Original description of the issue.',
         'staffadmin', 'Technical', 'Software', 'Triage', 'open'],
        ['Fresh ticket', 'A brand new and unrelated request.',
         'staffadmin', 'Technical', 'Software', 'Triage', 'open'],
    ])
    r = staff_client.post(
        '/admin/cases/import',
        data={'file': (csv_data, 'import.csv')},
        content_type='multipart/form-data',
    )
    assert r.status_code == 302
    # The duplicate row is not created a second time...
    assert _count(app, 'Existing ticket') == 1
    # ...while the distinct row imports normally.
    assert _count(app, 'Fresh ticket') == 1


def test_import_skips_intra_import_duplicate(staff_client, app):
    csv_data = _upload([
        ['Title', 'Description', 'Submitted By', 'Type', 'Category', 'Group', 'Status'],
        ['Duplicate row', 'Identical description text used twice.',
         'staffadmin', 'Technical', 'Software', 'Triage', 'open'],
        ['Duplicate row', 'Identical description text used twice.',
         'staffadmin', 'Technical', 'Software', 'Triage', 'open'],
    ])
    staff_client.post(
        '/admin/cases/import',
        data={'file': (csv_data, 'import.csv')},
        content_type='multipart/form-data',
    )
    # Second identical row within the same import is skipped.
    assert _count(app, 'Duplicate row') == 1


def test_import_ignores_soft_deleted_cases(staff_client, app):
    """A soft-deleted case must not block a fresh duplicate (F6 + F5 interaction)."""
    _seed_reference_data(app)
    made = _make_case(app, 'Closed dup', 'Old description.')
    from app import db as sql_db
    with app.app_context():
        made.deleted_at = datetime.utcnow() - timedelta(days=400)
        sql_db.session.commit()

    r = _submit(staff_client, 'Closed dup', 'Old description.')
    assert r.status_code == 200
    # The deleted case does not block creation; a new active case now exists.
    assert _count(app, 'Closed dup') == 1
