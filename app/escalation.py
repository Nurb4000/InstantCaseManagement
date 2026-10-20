"""Shared helpers for threshold-based escalation event logging (Q7).

SLA (app/sla.py) and OLA (app/ola.py) both "catch up" history when a case
crosses a threshold: if a case turns red but its yellow/orange milestones were
never logged (e.g. it jumped past them, or the process was down), those missing
events are backfilled so the timeline stays complete.

The backfill control flow is identical in both modules — a nested
"if this level is missing, log it" walk from the lowest threshold up to the
active one. This module centralises that flow so sla.py and ola.py only differ
in *how* they detect an existing event and build the details string, not in
*which* events get logged and in what order.
"""


def log_threshold_catchup(levels, current, has_event, log_and_notify):
    """Backfill any missing threshold events up to and including ``current``.

    Parameters
    ----------
    levels : sequence of str
        Level keys ordered from lowest to highest severity, e.g.
        ('yellow', 'orange', 'red'). Unknown keys (e.g. 'green') are a no-op.
    current : str or None
        The case's active level key.
    has_event(key) -> bool
        Returns True if an event for ``key`` already exists for the case.
    log_and_notify(key)
        Records the event and triggers escalation. Must persist (commit).
    """
    try:
        upto = levels.index(current)
    except ValueError:
        # 'green', None, or any unrecognised level -> nothing to backfill.
        return
    for key in levels[:upto + 1]:
        if not has_event(key):
            log_and_notify(key)
