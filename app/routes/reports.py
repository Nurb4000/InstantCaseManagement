import csv
from collections import Counter
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, Response
from flask_login import login_required, current_user
from io import StringIO

from app import db
from app.models import Case, Comment, SLAEvent, CaseType, Group
from app.routes.cases import _date_filter

reports_bp = Blueprint('reports', __name__, url_prefix='/reports')


def _sla_target_hours(case):
    ct = CaseType.query.filter_by(name=case.case_type).first()
    return ct.sla_hours if ct and ct.sla_hours else 0


def _breached_case_ids():
    rows = db.session.query(SLAEvent.case_id).filter_by(event_type='sla_red').all()
    return {r[0] for r in rows}


def _bucket_label(dt, granularity):
    if dt is None:
        return None
    if granularity == 'daily':
        return dt.strftime('%Y-%m-%d')
    if granularity == 'weekly':
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    return dt.strftime('%Y-%m')


def _volume_series(cases, granularity):
    counter = Counter()
    for c in cases:
        label = _bucket_label(c.created_date, granularity)
        if label:
            counter[label] += 1
    return [{'label': k, 'count': v} for k, v in sorted(counter.items())]


def _group_counts(cases):
    counter = Counter()
    for c in cases:
        counter[c.assignment_group.name if c.assignment_group else '(unassigned)'] += 1
    return counter


def _type_counts(cases):
    return Counter(c.case_type or '(none)' for c in cases)


def _status_counts(cases):
    return Counter((c.status or 'unknown').lower() for c in cases)


def _resolve_times(cases):
    times = []
    for c in cases:
        if c.created_date and c.resolved_date:
            hours = (c.resolved_date - c.created_date).total_seconds() / 3600.0
            if hours >= 0:
                times.append(hours)
    return times


def _first_response_times(cases):
    times = []
    for c in cases:
        first = (Comment.query.filter_by(case_id=c.id)
                 .order_by(Comment.created_date.asc())
                 .first())
        if first and c.created_date:
            hours = (first.created_date - c.created_date).total_seconds() / 3600.0
            if hours >= 0:
                times.append(hours)
    return times


def _resolved_by_agent(cases):
    counter = Counter()
    for c in cases:
        if c.status == 'resolved' and c.assigned_to is not None:
            counter[c.assigned_to.username] += 1
    return counter


def _format_hours(hours):
    if hours is None:
        return 'N/A'
    if hours < 1:
        return f'{int(round(hours * 60))}m'
    if hours < 24:
        return f'{hours:.1f}h'
    days = hours / 24.0
    if days < 30:
        return f'{days:.1f}d'
    months = days / 30.0
    return f'{months:.1f}mo'


def _report_data(cases, granularity):
    resolved = [c for c in cases if c.status == 'resolved']
    open_cases = [c for c in cases if c.status != 'resolved']

    breach_ids = _breached_case_ids()
    compliant_total = 0
    compliant_ok = 0
    breached_count = 0
    for c in resolved:
        if _sla_target_hours(c) <= 0:
            continue
        compliant_total += 1
        if c.id in breach_ids:
            breached_count += 1
        else:
            compliant_ok += 1
    compliance_rate = (compliant_ok / compliant_total * 100) if compliant_total else None

    resolve_times = _resolve_times(resolved)
    response_times = _first_response_times(cases)

    return {
        'total': len(cases),
        'open': len(open_cases),
        'resolved': len(resolved),
        'compliant_total': compliant_total,
        'compliant_ok': compliant_ok,
        'breached_count': breached_count,
        'compliance_rate': compliance_rate,
        'avg_resolve': sum(resolve_times) / len(resolve_times) if resolve_times else None,
        'avg_response': sum(response_times) / len(response_times) if response_times else None,
        'volume': _volume_series(cases, granularity),
        'by_group': _group_counts(cases),
        'by_type': _type_counts(cases),
        'by_status': _status_counts(cases),
        'resolved_by_agent': _resolved_by_agent(cases),
    }


def _apply_filters(query):
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    return _date_filter(query, date_from, date_to)


@reports_bp.route('/')
@login_required
def dashboard():
    if not current_user.is_staff and not current_user.is_admin:
        flash('Access denied')
        return redirect(url_for('cases.dashboard'))

    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    granularity = request.args.get('granularity', 'monthly')
    if granularity not in ('daily', 'weekly', 'monthly'):
        granularity = 'monthly'

    query = _apply_filters(Case.query)
    cases = query.order_by(Case.created_date.asc()).all()

    data = _report_data(cases, granularity)

    volume = data['volume']
    if volume:
        max_count = max(row['count'] for row in volume)
    else:
        max_count = 1
    for row in volume:
        row['pct'] = int(row['count'] / max_count * 100)

    def _bar_items(counter):
        items = sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))
        max_v = max((v for _, v in items), default=1) or 1
        return [{'label': k, 'count': v, 'pct': int(v / max_v * 100)} for k, v in items]

    by_group = _bar_items(data['by_group'])
    by_type = _bar_items(data['by_type'])
    by_status = _bar_items(data['by_status'])
    by_agent = _bar_items(data['resolved_by_agent'])

    return render_template(
        'reports/dashboard.html',
        data=data,
        granularity=granularity,
        date_from=date_from,
        date_to=date_to,
        by_group=by_group,
        by_type=by_type,
        by_status=by_status,
        by_agent=by_agent,
    )


@reports_bp.route('/export')
@login_required
def export():
    if not current_user.is_staff and not current_user.is_admin:
        flash('Access denied')
        return redirect(url_for('cases.dashboard'))

    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    granularity = request.args.get('granularity', 'monthly')
    if granularity not in ('daily', 'weekly', 'monthly'):
        granularity = 'monthly'

    query = _apply_filters(Case.query)
    cases = query.order_by(Case.created_date.asc()).all()
    data = _report_data(cases, granularity)

    out = StringIO()
    w = csv.writer(out)
    w.writerow(['Case-Tool Report — Reporting (F1)'])
    w.writerow([])
    w.writerow(['Metric', 'Value'])
    w.writerow(['Total cases', data['total']])
    w.writerow(['Open cases', data['open']])
    w.writerow(['Resolved cases', data['resolved']])
    w.writerow(['SLA compliance rate', f"{data['compliance_rate']:.1f}%" if data['compliance_rate'] is not None else 'N/A'])
    w.writerow(['Compliant cases', data['compliant_ok']])
    w.writerow(['Breached cases', data['breached_count']])
    w.writerow(['Avg first response', _format_hours(data['avg_response'])])
    w.writerow(['Avg resolution time', _format_hours(data['avg_resolve'])])
    w.writerow([])
    w.writerow(['Case volume by period', '', 'Granularity', granularity])
    for row in data['volume']:
        w.writerow([row['label'], row['count']])
    w.writerow([])
    w.writerow(['Cases by group'])
    for label, count in sorted(data['by_group'].items(), key=lambda kv: (-kv[1], str(kv[0]))):
        w.writerow([label, count])
    w.writerow([])
    w.writerow(['Cases by type'])
    for label, count in sorted(data['by_type'].items(), key=lambda kv: (-kv[1], str(kv[0]))):
        w.writerow([label, count])
    w.writerow([])
    w.writerow(['Cases by status'])
    for label, count in sorted(data['by_status'].items(), key=lambda kv: (-kv[1], str(kv[0]))):
        w.writerow([label, count])
    w.writerow([])
    w.writerow(['Resolved cases by agent'])
    for label, count in sorted(data['resolved_by_agent'].items(), key=lambda kv: (-kv[1], str(kv[0]))):
        w.writerow([label, count])

    return Response(out.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=reports.csv'})
