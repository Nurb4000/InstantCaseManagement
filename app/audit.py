"""F2: helper for recording administrative actions in the audit log.

``log_audit`` never raises — audit logging must not be able to break the
primary admin operation it is wrapping. If it cannot commit (e.g. a failing
session) it rolls back quietly rather than surfacing an error to the admin.
"""
from flask_login import current_user

from app import db
from app.models import AuditLog


def log_audit(action, *, target_type=None, target_id=None, details='', user=None):
    """Record a single administrative action.

    :param action: short machine-readable code, e.g. ``'user_create'``.
    :param target_type: model name the action targeted (``'User'``, ``'Group'``...).
    :param target_id: primary key of the targeted record, when applicable.
    :param details: free-form human-readable description.
    :param user: explicit actor; defaults to ``current_user`` when available.
    """
    actor = user
    if actor is None:
        try:
            actor = current_user
        except RuntimeError:
            actor = None

    actor_id = getattr(actor, 'id', None)
    actor_name = getattr(actor, 'username', None) or (user.username if user else None)

    entry = AuditLog(
        action=action,
        target_type=target_type,
        target_id=target_id,
        actor_user_id=actor_id,
        actor_name=actor_name,
        details=details or '',
    )
    db.session.add(entry)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
