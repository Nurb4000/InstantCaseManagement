from datetime import datetime, timedelta
from app import db
from app.models import OLAEvent, Group
from app.email import notify_escalation


def _get_thresholds(group):
    red = group.ola_hours if group and group.ola_hours else 2.0
    yellow = red * 0.7
    orange = red * 0.8
    return yellow, orange, red


def get_ola_color(elapsed_hours, group=None):
    if elapsed_hours is None:
        return None
    yellow, orange, red = _get_thresholds(group)
    if elapsed_hours >= red:
        return 'red'
    if elapsed_hours >= orange:
        return 'orange'
    if elapsed_hours >= yellow:
        return 'yellow'
    return 'green'


def get_business_hours_elapsed(start, now, group):
    if start is None or now is None or now <= start:
        return 0.0

    bh_start = group.business_hours_start if group and group.business_hours_start is not None else 6
    bh_end = group.business_hours_end if group and group.business_hours_end is not None else 18
    bh_days = set(group.business_hours_days.split(',')) if group and group.business_hours_days else {'Mon', 'Tue', 'Wed', 'Thu', 'Fri'}

    total = 0.0
    cursor = start.replace(hour=0, minute=0, second=0, microsecond=0)

    while cursor.date() <= now.date():
        day_name = cursor.strftime('%a')
        if day_name in bh_days:
            day_open = cursor.replace(hour=bh_start)
            day_close = cursor.replace(hour=bh_end)

            interval_start = max(start, day_open) if cursor.date() == start.date() else day_open
            interval_end = min(now, day_close) if cursor.date() == now.date() else day_close

            if interval_end > interval_start:
                total += (interval_end - interval_start).total_seconds() / 3600

        cursor += timedelta(days=1)

    return total


def _get_ola_group(case):
    if case.ola_group_id:
        return Group.query.get(case.ola_group_id)
    return case.assignment_group


def _ola_elapsed(case):
    return get_business_hours_elapsed(case.ola_started_at, datetime.utcnow(), _get_ola_group(case))


def _ola_log_and_notify(case, event_type, details):
    _log_event(case, event_type, details=details)
    label = event_type.replace('ola_', 'OLA ').title()
    notify_escalation(case, label, details)


# OLA escalation thresholds, lowest -> highest severity.
OLA_LEVELS = ('yellow', 'orange', 'red')


def _ola_details(level, elapsed):
    stamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    verb = {'yellow': 'approaching', 'orange': 'warning', 'red': 'breached'}[level]
    return f'OLA {verb} at {elapsed:.2f} business hours ({stamp} UTC)'


def _catch_up_events(case, color, elapsed):
    """Q7: backfill any missing OLA milestone events up to ``color``."""
    from app.escalation import log_threshold_catchup

    def has_event(key):
        return bool(OLAEvent.query.filter_by(case_id=case.id, event_type=f'ola_{key}').first())

    def log_and_notify(key):
        _ola_log_and_notify(case, f'ola_{key}', _ola_details(key, elapsed))

    log_threshold_catchup(OLA_LEVELS, color, has_event, log_and_notify)


def update_ola(case):
    if case.ola_started_at is None or case.status == 'resolved' or case.assigned_to_id is not None:
        case.ola_status = None
        return None

    elapsed = _ola_elapsed(case)
    group = _get_ola_group(case)
    color = get_ola_color(elapsed, group=group)
    _catch_up_events(case, color, elapsed)

    case.ola_status = color
    return color


def _log_event(case, event_type, group_name=None, details=None):
    event = OLAEvent(
        case_id=case.id,
        event_type=event_type,
        group_id=case.ola_group_id if group_name is None else None,
        group_name=group_name or (case.assignment_group.name if case.assignment_group else None),
        details=details,
        timestamp=datetime.utcnow()
    )
    db.session.add(event)
    db.session.commit()


def start_ola(case):
    case.ola_started_at = datetime.utcnow()
    case.ola_group_id = case.assignment_group_id
    db.session.commit()
    _log_event(case, 'group_assigned',
               group_name=case.assignment_group.name if case.assignment_group else None,
               details=f'OLA timer started for group "{case.assignment_group.name if case.assignment_group else "N/A"}"')


def stop_ola(case):
    if case.ola_started_at is None:
        return
    elapsed = _ola_elapsed(case)
    _log_event(case, 'ola_stopped',
               group_name=case.assignment_group.name if case.assignment_group else None,
               details=f'OLA stopped at {elapsed:.2f} business hours, assigned to user {case.assigned_to.username if case.assigned_to else "N/A"}')
    case.ola_started_at = None
    case.ola_group_id = None
    case.ola_status = None
    db.session.commit()


def restart_ola(case):
    if case.ola_started_at is not None:
        elapsed = _ola_elapsed(case)
        _log_event(case, 'ola_restarted',
                   group_name=case.assignment_group.name if case.assignment_group else None,
                   details=f'OLA restarted after {elapsed:.2f} business hours, new group "{case.assignment_group.name if case.assignment_group else "N/A"}"')
    case.ola_started_at = datetime.utcnow()
    case.ola_group_id = case.assignment_group_id
    db.session.commit()


def get_ola_elapsed(case):
    if case.ola_started_at is None:
        return 0.0
    return _ola_elapsed(case)
