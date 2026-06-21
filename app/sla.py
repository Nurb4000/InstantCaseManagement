from datetime import datetime, timedelta
from app import db
from app.models import SLAEvent, OrgSetting, CaseState
from app.email import notify_escalation

YELLOW_PCT = 70
ORANGE_PCT = 80


def get_sla_color(pct):
    if pct is None:
        return None
    if pct >= 100:
        return 'red'
    if pct >= ORANGE_PCT:
        return 'orange'
    if pct >= YELLOW_PCT:
        return 'yellow'
    return 'green'


def get_org_business_hours_elapsed(start, end):
    if start is None or end is None or end <= start:
        return 0.0

    org = OrgSetting.get()
    bh_start = org.business_hours_start or 6
    bh_end = org.business_hours_end or 18
    bh_days = set(org.business_hours_days.split(',')) if org.business_hours_days else {'Mon', 'Tue', 'Wed', 'Thu', 'Fri'}

    total = 0.0
    cursor = start.replace(hour=0, minute=0, second=0, microsecond=0)

    while cursor.date() <= end.date():
        day_name = cursor.strftime('%a')
        if day_name in bh_days:
            day_open = cursor.replace(hour=bh_start)
            day_close = cursor.replace(hour=bh_end)

            interval_start = max(start, day_open) if cursor.date() == start.date() else day_open
            interval_end = min(end, day_close) if cursor.date() == end.date() else day_close

            if interval_end > interval_start:
                total += (interval_end - interval_start).total_seconds() / 3600

        cursor += timedelta(days=1)

    return total


def _get_case_type_sla_hours(case):
    if not case.case_type:
        return 0
    ct = __import__('app.models', fromlist=['CaseType']).CaseType.query.filter_by(name=case.case_type).first()
    return ct.sla_hours if ct and ct.sla_hours else 0


def _get_effective_wall_seconds(case, now=None):
    if now is None:
        now = datetime.utcnow()
    if case.sla_started_at is None:
        return 0
    wall = (now - case.sla_started_at).total_seconds()
    paused = case.sla_total_paused_seconds or 0
    if case.sla_paused_at is not None:
        paused += (now - case.sla_paused_at).total_seconds()
    return max(0, wall - paused)


def _get_effective_wall_start(case):
    """Return the effective start time for SLA calculation, accounting for pauses."""
    if case.sla_started_at is None:
        return None, None

    total_paused = case.sla_total_paused_seconds or 0
    if case.sla_paused_at is not None:
        total_paused += (datetime.utcnow() - case.sla_paused_at).total_seconds()

    effective_start = case.sla_started_at + timedelta(seconds=total_paused)
    return effective_start, total_paused


def get_sla_elapsed(case):
    if case.sla_started_at is None or case.status == 'resolved':
        return 0.0

    eff_start, _ = _get_effective_wall_start(case)
    if eff_start is None:
        return 0.0

    now = datetime.utcnow()
    return get_org_business_hours_elapsed(eff_start, now)


def get_sla_pct(case):
    target = _get_case_type_sla_hours(case)
    if not target:
        return None
    elapsed = get_sla_elapsed(case)
    return (elapsed / target) * 100


def _log_and_notify(case, event_type, details):
    _log_sla_event(case, event_type, details=details)
    label = event_type.replace('sla_', 'SLA ').title()
    notify_escalation(case, label, details)


def update_sla(case):
    if case.status == 'resolved':
        case.sla_status = None
        return None

    pct = get_sla_pct(case)
    if pct is None:
        case.sla_status = None
        return None

    color = get_sla_color(pct)

    if color == 'red':
        if not SLAEvent.query.filter_by(case_id=case.id, event_type='sla_red').first():
            if not SLAEvent.query.filter_by(case_id=case.id, event_type='sla_orange').first():
                _log_and_notify(case, 'sla_orange',
                    f'SLA warning at {pct:.1f}% ({datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")} UTC)')
            if not SLAEvent.query.filter_by(case_id=case.id, event_type='sla_yellow').first():
                _log_and_notify(case, 'sla_yellow',
                    f'SLA approaching at {pct:.1f}% ({datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")} UTC)')
            _log_and_notify(case, 'sla_red',
                f'SLA breached at {pct:.1f}% ({datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")} UTC)')
    elif color == 'orange':
        if not SLAEvent.query.filter_by(case_id=case.id, event_type='sla_orange').first():
            if not SLAEvent.query.filter_by(case_id=case.id, event_type='sla_yellow').first():
                _log_and_notify(case, 'sla_yellow',
                    f'SLA approaching at {pct:.1f}% ({datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")} UTC)')
            _log_and_notify(case, 'sla_orange',
                f'SLA warning at {pct:.1f}% ({datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")} UTC)')
    elif color == 'yellow':
        if not SLAEvent.query.filter_by(case_id=case.id, event_type='sla_yellow').first():
            _log_and_notify(case, 'sla_yellow',
                f'SLA approaching at {pct:.1f}% ({datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")} UTC)')

    case.sla_status = color
    return color


def _log_sla_event(case, event_type, details=None):
    event = SLAEvent(
        case_id=case.id,
        event_type=event_type,
        details=details,
        timestamp=datetime.utcnow()
    )
    db.session.add(event)
    db.session.commit()


def start_sla(case):
    case.sla_started_at = datetime.utcnow()
    case.sla_paused_at = None
    case.sla_total_paused_seconds = 0
    db.session.commit()
    target = _get_case_type_sla_hours(case)
    _log_sla_event(case, 'sla_started',
                   details=f'SLA timer started for type "{case.case_type or "N/A"}" with target {target}h')


def stop_sla(case):
    if case.sla_started_at is None:
        return
    elapsed = get_sla_elapsed(case)
    target = _get_case_type_sla_hours(case)
    _log_sla_event(case, 'sla_stopped',
                   details=f'SLA stopped at {elapsed:.2f} business hours (target {target}h)')
    case.sla_started_at = None
    case.sla_paused_at = None
    case.sla_total_paused_seconds = 0
    case.sla_status = None
    db.session.commit()


def pause_sla(case):
    if case.sla_started_at is None or case.sla_paused_at is not None:
        return
    case.sla_paused_at = datetime.utcnow()
    db.session.commit()
    _log_sla_event(case, 'sla_paused',
                   details=f'SLA paused at state change to "Waiting on Resolution Approval"')
    return True


def resume_sla(case):
    if case.sla_started_at is None or case.sla_paused_at is None:
        return
    paused_seconds = (datetime.utcnow() - case.sla_paused_at).total_seconds()
    case.sla_total_paused_seconds = (case.sla_total_paused_seconds or 0) + int(paused_seconds)
    case.sla_paused_at = None
    db.session.commit()
    _log_sla_event(case, 'sla_resumed',
                   details=f'SLA resumed after {paused_seconds:.0f}s paused')
    return True


def recalculate_sla(case, old_type_name=None):
    """Recalculate SLA when case type changes. Does not reset the clock."""
    target = _get_case_type_sla_hours(case)
    elapsed = get_sla_elapsed(case)
    pct = (elapsed / target) * 100 if target else 0
    _log_sla_event(case, 'sla_recalculated',
                   details=f'SLA recalculated: type changed from "{old_type_name or "?"}" to "{case.case_type or "N/A"}", target {target}h, elapsed {elapsed:.2f}h ({pct:.1f}%)')
