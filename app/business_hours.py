"""Q5: business-hours elapsed-time math shared by SLA and OLA.

Both ``app/sla.py`` (org-wide business hours) and ``app/ola.py`` (per-group
business hours) compute how many business hours elapse between two instants.
The logic is identical, so it lives here once.

Historically this iterated day-by-day across the whole window
(``while cursor.date() <= end.date()``). That is fine for a few days but
wasteful for multi-year SLA windows (thousands of iterations). The month-granularity
implementation below counts full interior months in O(1) via ``calendar`` and
only touches the partial first/last days and edge months explicitly, so cost
scales with the number of months rather than the number of days.

Behavior is identical to the day-by-day version (verified by a differential
test in ``tests/test_business_hours.py``).
"""
import calendar
from datetime import datetime, timedelta

from app.models import OrgSetting


def _biz_weekday_indices(bh_days):
    """Map the ``bh_days`` labels (compared via ``strftime('%a')``) to Python
    weekday indices (Mon=0 .. Sun=6).

    Built by checking each of the seven reference weekdays with the *same*
    ``strftime('%a')`` the caller uses, so this stays correct regardless of the
    active locale and matches the old membership test exactly.
    """
    indices = set()
    for ref in range(1, 8):  # 2026-03-01 is a Monday; covers all seven weekdays
        if datetime(2026, 3, ref).strftime('%a') in bh_days:
            indices.add(datetime(2026, 3, ref).weekday())
    return indices


def _single_day_hours(d, lo, hi, bh_start, bh_end):
    """Business hours within a single calendar day ``d`` for the sub-range
    ``[lo, hi]``, clamped to the day's ``[bh_start, bh_end]`` window."""
    day_open = datetime(d.year, d.month, d.day, bh_start)
    day_close = datetime(d.year, d.month, d.day, bh_end)
    if day_close <= day_open:
        return 0.0
    lo = max(lo, day_open)
    hi = min(hi, day_close)
    if hi <= lo:
        return 0.0
    return (hi - lo).total_seconds() / 3600.0


def _business_days_in_full_month(year, month, biz):
    """Count business days in a complete calendar month in O(7)."""
    first_weekday, last_day = calendar.monthrange(year, month)
    total = 0
    for w in biz:
        first = ((w - first_weekday) % 7) + 1
        if first > last_day:
            continue
        total += (last_day - first) // 7 + 1
    return total


def _count_business_days(a_date, b_date, biz):
    """Number of business days in the inclusive date range ``[a_date, b_date]``.

    Full months are counted in O(1); the partial edge months iterate their
    days (at most ~31 each).
    """
    if a_date > b_date:
        return 0
    count = 0
    cur = a_date.replace(day=1)
    while cur <= b_date:
        _, last_day = calendar.monthrange(cur.year, cur.month)
        month_last = cur.replace(day=last_day)
        seg_a = max(cur, a_date)
        seg_b = min(month_last, b_date)
        if seg_a == seg_b:
            if seg_a.weekday() in biz:
                count += 1
        elif seg_a.day == 1 and seg_b.day == last_day:
            count += _business_days_in_full_month(cur.year, cur.month, biz)
        else:
            d = seg_a
            while d <= seg_b:
                if d.weekday() in biz:
                    count += 1
                d += timedelta(days=1)
        # Advance to the first day of the *next* month. Adding 31 days to the
        # 1st always crosses into a later month, so .replace(day=1) is safe.
        cur = (seg_b.replace(day=1) + timedelta(days=31)).replace(day=1)
    return count


def _business_hours_elapsed(start, end, bh_start, bh_end, bh_days):
    """Business hours between ``start`` and ``end`` (see module docstring)."""
    if start is None or end is None or end <= start:
        return 0.0

    biz = _biz_weekday_indices(bh_days)
    bh_span = bh_end - bh_start
    if bh_span <= 0:
        return 0.0

    def _is_biz(d):
        return d.weekday() in biz

    s_date = start.date()
    e_date = end.date()

    if _is_biz(s_date) and s_date == e_date:
        return _single_day_hours(s_date, start, end, bh_start, bh_end)

    total = 0.0
    # Partial first day: from `start` up to the close of its business window.
    if _is_biz(s_date):
        total += _single_day_hours(s_date, start, _end_of_day(s_date), bh_start, bh_end)
    # Full interior days (strictly between first and last day).
    interior_last = e_date - timedelta(days=1)
    if interior_last > s_date:
        n = _count_business_days(s_date + timedelta(days=1), interior_last, biz)
        total += n * bh_span
    # Partial last day: from the open of its business window up to `end`.
    if _is_biz(e_date):
        total += _single_day_hours(e_date, _start_of_day(e_date), end, bh_start, bh_end)
    return total


def _start_of_day(d):
    return datetime(d.year, d.month, d.day)


def _end_of_day(d):
    return datetime(d.year, d.month, d.day, 23, 59, 59, 999999)


def org_business_hours_elapsed(start, end):
    """Business hours per the organization's settings (used by SLA)."""
    if start is None or end is None or end <= start:
        return 0.0
    org = OrgSetting.get()
    bh_start = org.business_hours_start or 6
    bh_end = org.business_hours_end or 18
    bh_days = set(org.business_hours_days.split(',')) if org.business_hours_days else {'Mon', 'Tue', 'Wed', 'Thu', 'Fri'}
    return _business_hours_elapsed(start, end, bh_start, bh_end, bh_days)


def group_business_hours_elapsed(start, now, group):
    """Business hours for a single group (used by OLA)."""
    if start is None or now is None or now <= start:
        return 0.0
    bh_start = group.business_hours_start if group and group.business_hours_start is not None else 6
    bh_end = group.business_hours_end if group and group.business_hours_end is not None else 18
    bh_days = set(group.business_hours_days.split(',')) if group and group.business_hours_days else {'Mon', 'Tue', 'Wed', 'Thu', 'Fri'}
    return _business_hours_elapsed(start, now, bh_start, bh_end, bh_days)
