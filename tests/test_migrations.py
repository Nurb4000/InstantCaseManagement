"""Q2 regression: the live DB schema (built by Flask-Migrate in create_app)
must stay consistent with the ORM models.

The app builds its schema via alembic migrations, not db.create_all(), so a
model change that isn't mirrored in a migration would silently drift from the
database. This test inspects the migrated schema after ``create_app`` and
asserts it matches the models — columns present/absent, nullable flags, and
model-defined indexes. Catches both missing columns (migration forgot to add
them) and extra columns (migration left stale ones behind).
"""
import sqlalchemy as sa

from app import db


def _migrated_columns(insp, table):
    return {c['name']: c for c in insp.get_columns(table)}


def test_migrations_match_models(app):
    with app.app_context():
        insp = sa.inspect(db.engine)
        tables = set(insp.get_table_names())

        from app.models import (  # noqa: F401  (import for side-effect registration)
            Case, User, Group, OrgSetting, CaseState, CaseType, CaseCategory,
            Attachment, Comment, EmailLog, SLAEvent, OLAEvent, AuditLog,
            LoginAttempt,
        )
        models = [Case, User, Group, OrgSetting, CaseState, CaseType,
                  CaseCategory, Attachment, Comment, EmailLog, SLAEvent,
                  OLAEvent, AuditLog, LoginAttempt]

        problems = []
        for model in models:
            name = model.__tablename__
            if name not in tables:
                problems.append(f'{name}: table missing from migrated DB')
                continue
            cols_db = _migrated_columns(insp, name)
            model_cols = {c.name: c for c in model.__table__.columns}

            for cn in model_cols:
                if cn not in cols_db:
                    problems.append(f'{name}.{cn}: column missing in DB')
            for cn in cols_db:
                if cn not in model_cols:
                    problems.append(f'{name}.{cn}: stale column in DB (not in model)')
            for cn, cdef in cols_db.items():
                if cn in model_cols:
                    db_null = cdef.get('nullable', True)
                    mdl_null = model_cols[cn].nullable
                    if db_null != mdl_null:
                        problems.append(
                            f'{name}.{cn}: nullable DB={db_null} MODEL={mdl_null}'
                        )

            # model-defined indexes must exist in the migrated schema
            db_indexes = {(tuple(i['column_names']), i['unique'])
                          for i in insp.get_indexes(name)}
            for idx in model.__table__.indexes:
                cols = tuple(c.name for c in idx.columns)
                if not any(set(dcols) == set(cols) and u == idx.unique
                           for dcols, u in db_indexes):
                    problems.append(f'{name}.{idx.name or cols}: index missing in DB')

        assert not problems, 'Schema/migration drift:\n' + '\n'.join(problems)
