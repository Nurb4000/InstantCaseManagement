"""Q4: single consistent timezone policy.

Datetimes are stored as naive UTC and only ever rendered through the
``local_fmt`` Jinja filter, which converts to local wall-clock time in a
DST-safe way. These tests lock that behaviour and guard against templates
bypassing the filter with a raw .strftime() (which would print the UTC label).
"""
from datetime import datetime, timedelta, timezone


def _fmt(app):
    return app.jinja_env.filters['local_fmt']


def test_local_fmt_none_returns_empty(app):
    assert _fmt(app)(None) == ''


def test_local_fmt_naive_utc_matches_reference_conversion(app):
    """A naive (stored-UTC) datetime converts to local exactly as astimezone
    says — so it is correct across any DST transition in the host zone."""
    fmt = '%Y-%m-%d %H:%M'
    naive_utc = datetime(2026, 7, 1, 12, 30)  # naive, assumed UTC
    expected = naive_utc.replace(tzinfo=timezone.utc).astimezone().strftime(fmt)
    assert _fmt(app)(naive_utc, fmt) == expected


def test_local_fmt_aware_datetime_not_corrupted(app):
    """An already-aware datetime must be converted as-is, not force-UTC'd."""
    fmt = '%Y-%m-%d %H:%M'
    aware_plus_two = datetime(2026, 7, 1, 12, 30, tzinfo=timezone(timedelta(hours=2)))
    # Converting a +02:00 value to local must differ from treating it as UTC...
    expected = aware_plus_two.astimezone().strftime(fmt)
    assert _fmt(app)(aware_plus_two, fmt) == expected
    # ...and must not equal the naive-UTC interpretation of the same wall time.
    naive_as_utc = _fmt(app)(datetime(2026, 7, 1, 12, 30), fmt)
    assert expected != naive_as_utc


def test_local_fmt_dst_boundary(app, monkeypatch):
    """Across a spring-forward the local hour must jump by an hour. A naive
    strftime on the stored UTC value would ignore DST entirely; astimezone
    (used by local_fmt) honours it."""
    import time
    fmt = '%Y-%m-%d %H:%M'
    # America/New_York springs forward 2026-03-08 at 07:00 UTC (2:00 EST -> 3:00 EDT).
    monkeypatch.setenv('TZ', 'America/New_York')
    time.tzset()
    before = datetime(2026, 3, 8, 6, 59)   # 01:59 EST (UTC-5)
    after = datetime(2026, 3, 8, 7, 1)      # 03:01 EDT (UTC-4), 2 min later in UTC
    h_before = int(_fmt(app)(before, '%H'))
    h_after = int(_fmt(app)(after, '%H'))
    # The spring-forward skips the 03:00 hour, so local hours jump by 2 even
    # though the UTC instants are only 2 minutes apart (a naive strftime would
    # never show this DST behaviour).
    assert h_after - h_before == 2


def test_no_template_uses_raw_strftime():
    """Regression guard: no template may format a stored datetime directly;
    all display must go through local_fmt (which converts to local time)."""
    import glob
    import os
    root = os.path.join(os.path.dirname(__file__), '..', 'templates')
    files = glob.glob(os.path.join(root, '**', '*.html'), recursive=True)
    for path in files:
        with open(path, 'r', encoding='utf-8') as fh:
            src = fh.read()
        assert '.strftime(' not in src, f'{path} formats a datetime without local_fmt'
