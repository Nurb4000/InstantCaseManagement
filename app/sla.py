import os
from datetime import datetime, timedelta
from app import db
from app.models import SLAEvent, OrgSetting, CaseState, CaseType
from app.email import notify_escalation
from app.business_hours import org_business_hours_elapsed as _org_business_hours_elapsed

YELLOW_PCT = 70
ORANGE_PCT = 80

# Safety valve (hours): an SLA pause that stays open longer than this is treated
# as stuck (e.g. the process crashed while a case was paused) and is auto-resumed
# so the SLA clock cannot freeze forever. Intentional customer-wait pauses are
# shorter than this threshold by design. Configurable via the STUCK_SLA_PAUSE_HOURS
# environment variable.
STUCK_SLA_PAUSE_HOURS = float(os.environ.get('STUCK_SLA_PAUSE_HOURS', '720'))


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
    # Q5: business-hours math delegated to app.business_hours (month-granular).
    return _org_business_hours_elapsed(start, end)


def _get_case_type_sla_hours(case):
    if not case.case_type:
        return 0
    ct = CaseType.query.filter_by(name=case.case_type).first()
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


# SLA escalation thresholds, lowest -> highest severity.
SLA_LEVELS = ('yellow', 'orange', 'red')


def _sla_details(level, pct):
    stamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    verb = {'yellow': 'approaching', 'orange': 'warning', 'red': 'breached'}[level]
    return f'SLA {verb} at {pct:.1f}% ({stamp} UTC)'


def _catch_up_events(case, color, pct):
    """Q7: backfill any missing SLA milestone events up to ``color``."""
    from app.escalation import log_threshold_catchup

    def has_event(key):
        return bool(SLAEvent.query.filter_by(case_id=case.id, event_type=f'sla_{key}').first())

    def log_and_notify(key):
        _log_and_notify(case, f'sla_{key}', _sla_details(key, pct))

    log_threshold_catchup(SLA_LEVELS, color, has_event, log_and_notify)


def update_sla(case):
    if case.status == 'resolved':
        case.sla_status = None
        return None

    # B4 recovery: an SLA pause left open past the safety valve (e.g. after a
    # crash) would otherwise freeze the clock forever. Auto-resume it so SLA
    # progress can continue. Intentional customer-wait pauses are shorter than
    # STUCK_SLA_PAUSE_HOURS by design.
    if case.sla_paused_at is not None:
        paused_for = (datetime.utcnow() - case.sla_paused_at).total_seconds() / 3600.0
        if paused_for > STUCK_SLA_PAUSE_HOURS:
            resume_sla(case, reason=f'auto-resumed after stuck pause open {paused_for:.1f}h')

    pct = get_sla_pct(case)
    if pct is None:
        case.sla_status = None
        return None

    color = get_sla_color(pct)
    _catch_up_events(case, color, pct)

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


def resume_sla(case, reason=None):
    if case.sla_started_at is None or case.sla_paused_at is None:
        return
    paused_seconds = (datetime.utcnow() - case.sla_paused_at).total_seconds()
    case.sla_total_paused_seconds = (case.sla_total_paused_seconds or 0) + int(paused_seconds)
    case.sla_paused_at = None
    db.session.commit()
    detail = f'SLA resumed after {paused_seconds:.0f}s paused'
    if reason:
        detail += f' ({reason})'
    _log_sla_event(case, 'sla_resumed', details=detail)
    return True


def recalculate_sla(case, old_type_name=None):
    """Recalculate SLA when case type changes. Does not reset the clock."""
    target = _get_case_type_sla_hours(case)
    elapsed = get_sla_elapsed(case)
    pct = (elapsed / target) * 100 if target else 0
    _log_sla_event(case, 'sla_recalculated',
                   details=f'SLA recalculated: type changed from "{old_type_name or "?"}" to "{case.case_type or "N/A"}", target {target}h, elapsed {elapsed:.2f}h ({pct:.1f}%)')
