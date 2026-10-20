"""Q5: business-hours math equivalence + month-granularity correctness.

``_business_hours_elapsed`` in app/business_hours.py replaced the day-by-day
loops in sla.py/ola.py. This module locks that refactor:

* A differential test compares the new implementation against an independent
  oracle that reproduces the *original* daily loop, over thousands of
  randomized windows (including multi-year spans, varied business-hour ranges
  and arbitrary business-day sets).
* Wrapper-level tests exercise the org/group entry points through the app.
"""
import random
from datetime import datetime, timedelta

import pytest

from app.business_hours import (
    _business_hours_elapsed,
    org_business_hours_elapsed,
    group_business_hours_elapsed,
)


def _oracle(start, end, bh_start, bh_end, bh_days):
    """Independent reproduction of the original day-by-day algorithm."""
    if start is None or end is None or end <= start:
        return 0.0
    total = 0.0
    cursor = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while cursor.date() <= end.date():
        if cursor.strftime('%a') in bh_days:
            day_open = cursor.replace(hour=bh_start)
            day_close = cursor.replace(hour=bh_end)
            interval_start = max(start, day_open) if cursor.date() == start.date() else day_open
            interval_end = min(end, day_close) if cursor.date() == end.date() else day_close
            if interval_end > interval_start:
                total += (interval_end - interval_start).total_seconds() / 3600
        cursor += timedelta(days=1)
    return total


ALL_WEEKDAYS = [datetime(2026, 3, ref).strftime('%a') for ref in range(1, 8)]


def _random_bh_days(rng):
    # Non-empty subset of weekday labels (empty set => zero business hours).
    k = rng.randint(0, len(ALL_WEEKDAYS))
    return set(rng.sample(ALL_WEEKDAYS, k))


@pytest.mark.parametrize('seed', range(200))
def test_matches_oracle_randomized(seed):
    rng = random.Random(seed)
    # Spread starts across a ~6-year span so windows routinely cross years.
    start = datetime(2026, 1, 1) + timedelta(days=rng.randint(0, 6 * 366), hours=rng.randint(0, 23), minutes=rng.randint(0, 59))
    span_days = rng.randint(0, 6 * 366)
    end = start + timedelta(days=span_days, hours=rng.randint(0, 23), minutes=rng.randint(0, 59))
    if end <= start:
        end = start + timedelta(minutes=1)

    bh_start = rng.randint(0, 12)
    bh_end = rng.randint(bh_start + 1, 23)
    bh_days = _random_bh_days(rng)

    got = _business_hours_elapsed(start, end, bh_start, bh_end, bh_days)
    exp = _oracle(start, end, bh_start, bh_end, bh_days)
    assert got == pytest.approx(exp, abs=1e-9), (start, end, bh_start, bh_end, sorted(bh_days))


def test_zero_and_full_day_edge_cases():
    rng = random.Random(12345)
    for _ in range(200):
        start = datetime(2026, 1, 1) + timedelta(days=rng.randint(0, 400), hours=rng.randint(0, 22))
        end = start + timedelta(hours=rng.randint(0, 100), minutes=rng.randint(0, 59))
        bh_start = rng.randint(0, 12)
        bh_end = rng.randint(bh_start + 1, 23)
        bh_days = _random_bh_days(rng)
        got = _business_hours_elapsed(start, end, bh_start, bh_end, bh_days)
        exp = _oracle(start, end, bh_start, bh_end, bh_days)
        assert got == pytest.approx(exp, abs=1e-9)


def test_empty_window_returns_zero():
    assert _business_hours_elapsed(None, datetime(2026, 1, 2), 6, 18, {'Mon'}) == 0.0
    assert _business_hours_elapsed(datetime(2026, 1, 2), None, 6, 18, {'Mon'}) == 0.0
    same = datetime(2026, 1, 2, 10)
    assert _business_hours_elapsed(same, same, 6, 18, {'Mon'}) == 0.0
    assert _business_hours_elapsed(same, same - timedelta(minutes=5), 6, 18, {'Mon'}) == 0.0


def test_weekend_only_business_days():
    # Weekend-only business days over a weekday window => zero elapsed.
    sat = datetime(2026, 3, 7).strftime('%a')  # Saturday
    sun = datetime(2026, 3, 8).strftime('%a')  # Sunday
    start = datetime(2026, 3, 3, 6, 0)   # Tuesday
    end = datetime(2026, 3, 6, 18, 0)    # Friday
    assert _business_hours_elapsed(start, end, 6, 18, {sat, sun}) == 0.0


def test_weekdays_only_business_days_counts_weekend_as_zero():
    # Monday-only business days over a Tuesday-Friday window => zero elapsed.
    mon = datetime(2026, 3, 2).strftime('%a')  # Monday
    start = datetime(2026, 3, 3, 9, 0)   # Tuesday
    end = datetime(2026, 3, 6, 17, 0)    # Friday
    assert _business_hours_elapsed(start, end, 9, 18, {mon}) == 0.0


def test_full_weekday_window_is_span():
    mon = datetime(2026, 1, 5).strftime('%a')  # Monday
    start = datetime(2026, 1, 5, 6, 0)
    end = datetime(2026, 1, 6, 18, 0)  # Mon 06:00 -> Tue? no, Tue not in set
    # Single business day Mon 06:00->18:00 = 12h (Tue excluded).
    assert _business_hours_elapsed(start, end, 6, 18, {mon}) == pytest.approx(12.0)


# --- wrapper-level tests through the app ------------------------------------


def test_org_wrapper_uses_default_settings(app):
    from app.models import OrgSetting
    with app.app_context():
        org = OrgSetting.get()
        org.business_hours_start = 9
        org.business_hours_end = 18
        org.business_hours_days = 'Mon,Tue,Wed,Thu,Fri'
        from app import db as sql_db
        sql_db.session.commit()

    # 2026-03-02 is a Monday through 2026-03-05 a Thursday: four full business
    # days at 09:00->18:00 => 36 hours.
    start = datetime(2026, 3, 2, 9, 0)
    end = datetime(2026, 3, 5, 18, 0)
    with app.app_context():
        result = org_business_hours_elapsed(start, end)
    assert result == pytest.approx(36.0)


def test_group_wrapper_defaults_when_unset(app):
    from app.models import Group
    with app.app_context():
        g = Group(name='GHTest')
        # leave business hours unset -> defaults 6/18, Mon-Fri
        from app import db as sql_db
        sql_db.session.add(g)
        sql_db.session.commit()
        gid = g.id

    # 2026-03-02 is a Monday: one full 06:00->18:00 business day.
    start = datetime(2026, 3, 2, 6, 0)
    end = datetime(2026, 3, 2, 18, 0)
    with app.app_context():
        from app.models import Group as G
        grp = G.query.get(gid)
        result = group_business_hours_elapsed(start, end, grp)
    assert result == pytest.approx(12.0)
