import os
import uuid
from datetime import datetime, timedelta
import csv
from io import StringIO
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, current_app, Response
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app import db
from app.models import Case, Comment, Attachment, User, Group, CaseState, CaseType, CaseCategory
from app.forms import CaseForm, CommentForm, AssignForm, EditCaseForm

cases_bp = Blueprint('cases', __name__)

ALLOWED_EXTENSIONS = {
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'txt', 'csv', 'png', 'jpg', 'jpeg', 'gif', 'zip',
}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def user_group_ids(user):
    return [g.id for g in user.groups]


def _search_filter(query, q, field='all'):
    if not q:
        return query
    like = f'%{q}%'
    Submitter = db.aliased(User)
    Assignee = db.aliased(User)
    field_map = {
        'title': Case.title.ilike(like),
        'description': Case.description.ilike(like),
        'type': Case.case_type.ilike(like),
        'category': Case.category.ilike(like),
        'status': Case.status.ilike(like),
        'submitted_for': Case.submitted_for.ilike(like),
        'id': Case.id == (int(q) if q.isdigit() else 0),
        'submitted_by': Submitter.username.ilike(like),
        'assigned_to': Assignee.username.ilike(like),
        'group': Group.name.ilike(like),
    }
    if field in field_map:
        if field == 'submitted_by':
            return query.join(Submitter, Case.user_id == Submitter.id).filter(field_map[field])
        if field == 'assigned_to':
            return query.outerjoin(Assignee, Case.assigned_to_id == Assignee.id).filter(field_map[field])
        if field == 'group':
            return query.outerjoin(Group, Case.assignment_group_id == Group.id).filter(field_map[field])
        return query.filter(field_map[field])
    return query.filter(db.or_(*field_map.values()))


def _date_filter(query, date_from, date_to):
    if date_from:
        query = query.filter(Case.created_date >= datetime.strptime(date_from, '%Y-%m-%d'))
    if date_to:
        query = query.filter(Case.created_date <= datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
    return query


@cases_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('cases.dashboard'))
    marketing_enabled = os.environ.get('MARKETING_ENABLED', 'true').lower() in ('1', 'true', 'yes')
    return render_template('index.html', marketing_enabled=marketing_enabled)


@cases_bp.route('/dashboard')
@login_required
def dashboard():
    q = request.args.get('q', '').strip()
    field = request.args.get('field', 'all')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    def _base(query):
        return _date_filter(_search_filter(query, q, field), date_from, date_to)

    if current_user.is_staff:
        group_ids = user_group_ids(current_user)
        assigned_cases = _base(Case.query.filter(
            Case.assigned_to_id == current_user.id,
            Case.status != 'resolved'
        )).all()
        unassigned_cases = _base(Case.query.filter(
            Case.assignment_group_id.in_(group_ids),
            Case.assigned_to_id == None,
            Case.status != 'resolved'
        )).all() if group_ids else []
        team_cases = _base(Case.query.filter(
            Case.assignment_group_id.in_(group_ids),
            Case.assigned_to_id != None,
            Case.assigned_to_id != current_user.id,
            Case.status != 'resolved'
        )).all() if group_ids else []
        return render_template('staff_dashboard.html',
                               assigned_cases=assigned_cases,
                               unassigned_cases=unassigned_cases,
                               team_cases=team_cases,
                               q=q, field=field, date_from=date_from, date_to=date_to)
    else:
        user_cases = _base(Case.query.filter_by(user_id=current_user.id)).all()
        return render_template('user_dashboard.html', cases=user_cases, q=q, field=field, date_from=date_from, date_to=date_to)


@cases_bp.route('/cases')
@login_required
def all_cases():
    if not current_user.is_staff and not current_user.is_admin:
        flash('Access denied')
        return redirect(url_for('cases.dashboard'))
    q = request.args.get('q', '').strip()
    field = request.args.get('field', 'all')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    show_resolved = request.args.get('resolved', '0') == '1'
    query = Case.query
    if not show_resolved:
        query = query.filter(Case.status != 'resolved')
    query = _date_filter(_search_filter(query, q, field), date_from, date_to)
    cases = query.order_by(Case.created_date.desc()).all()
    return render_template('admin/cases.html', cases=cases, show_resolved=show_resolved, q=q, field=field, date_from=date_from, date_to=date_to)


def _csv_response(cases, filename):
    out = StringIO()
    w = csv.writer(out)
    w.writerow(['ID', 'Title', 'Description', 'Submitted By', 'Submitted For',
                'Assigned To', 'Group', 'State', 'Status', 'Type', 'Category',
                'Created', 'Resolved'])
    for c in cases:
        w.writerow([c.id, c.title, c.description, c.user.username,
                    c.submitted_for or '',
                    c.assigned_to.username if c.assigned_to else '',
                    c.assignment_group.name if c.assignment_group else '',
                    c.state.name if c.state else '', c.status, c.case_type,
                    c.category, c.created_date, c.resolved_date or ''])
    return Response(out.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename={filename}'})


@cases_bp.route('/export/assigned')
@login_required
def export_assigned():
    if not current_user.is_staff:
        return redirect(url_for('cases.dashboard'))
    q = request.args.get('q', '').strip()
    field = request.args.get('field', 'all')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    cases = _date_filter(_search_filter(Case.query.filter(
        Case.assigned_to_id == current_user.id,
        Case.status != 'resolved'
    ), q, field), date_from, date_to).order_by(Case.created_date.desc()).all()
    return _csv_response(cases, 'assigned_cases.csv')


@cases_bp.route('/export/unassigned')
@login_required
def export_unassigned():
    if not current_user.is_staff:
        return redirect(url_for('cases.dashboard'))
    q = request.args.get('q', '').strip()
    field = request.args.get('field', 'all')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    group_ids = user_group_ids(current_user)
    cases = _date_filter(_search_filter(Case.query.filter(
        Case.assignment_group_id.in_(group_ids),
        Case.assigned_to_id == None,
        Case.status != 'resolved'
    ), q, field), date_from, date_to).order_by(Case.created_date.desc()).all() if group_ids else []
    return _csv_response(cases, 'unassigned_cases.csv')


@cases_bp.route('/export/team')
@login_required
def export_team():
    if not current_user.is_staff:
        return redirect(url_for('cases.dashboard'))
    q = request.args.get('q', '').strip()
    field = request.args.get('field', 'all')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    group_ids = user_group_ids(current_user)
    cases = _date_filter(_search_filter(Case.query.filter(
        Case.assignment_group_id.in_(group_ids),
        Case.assigned_to_id != None,
        Case.assigned_to_id != current_user.id,
        Case.status != 'resolved'
    ), q, field), date_from, date_to).order_by(Case.created_date.desc()).all() if group_ids else []
    return _csv_response(cases, 'team_cases.csv')


@cases_bp.route('/export/user')
@login_required
def export_user():
    q = request.args.get('q', '').strip()
    field = request.args.get('field', 'all')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    cases = _date_filter(_search_filter(Case.query.filter_by(user_id=current_user.id), q, field), date_from, date_to).order_by(Case.created_date.desc()).all()
    return _csv_response(cases, 'my_cases.csv')


@cases_bp.route('/export/all')
@login_required
def export_all_cases():
    if not current_user.is_staff:
        return redirect(url_for('cases.dashboard'))
    q = request.args.get('q', '').strip()
    field = request.args.get('field', 'all')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    show_resolved = request.args.get('resolved', '0') == '1'
    query = Case.query
    if not show_resolved:
        query = query.filter(Case.status != 'resolved')
    query = _date_filter(_search_filter(query, q, field), date_from, date_to)
    cases = query.order_by(Case.created_date.desc()).all()
    return _csv_response(cases, 'all_cases.csv')


@cases_bp.route('/submit_case', methods=['GET', 'POST'])
@login_required
def submit_case():
    form = CaseForm()
    form.case_type.choices = [('', 'Select a type')] + [(t.name, t.name) for t in CaseType.query.order_by(CaseType.sort_order).all()]
    form.category.choices = [('', 'Select a category')] + [(c.name, c.name) for c in CaseCategory.query.filter_by(hidden=False).order_by(CaseCategory.sort_order).all()]
    new_state = CaseState.query.filter_by(name='New').first()
    if current_user.is_staff:
        states = CaseState.query.filter_by(hidden=False).order_by(CaseState.sort_order).all()
        form.state_id.choices = [(s.id, s.name) for s in states]
    else:
        del form.state_id
    if not form.submitted_for.data:
        form.submitted_for.data = current_user.username
    if form.validate_on_submit():
        triage_group = Group.query.filter_by(name='Triage').first()
        case = Case(
            title=form.title.data,
            description=form.description.data,
            case_type=form.case_type.data,
            category=form.category.data,
            user_id=current_user.id,
            assignment_group_id=triage_group.id if triage_group else None,
            state_id=form.state_id.data if current_user.is_staff and form.state_id.data else (new_state.id if new_state else None),
            submitted_for=form.submitted_for.data,
        )
        db.session.add(case)
        db.session.commit()
        flash('Case submitted successfully')
        return redirect(url_for('cases.dashboard'))
    return render_template('submit_case.html', form=form)


@cases_bp.route('/case/<int:case_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_case(case_id):
    case = Case.query.get_or_404(case_id)
    if not current_user.is_staff and case.user_id != current_user.id:
        flash('Access denied')
        return redirect(url_for('cases.dashboard'))
    if not current_user.is_staff and case.user_id == current_user.id and case.status != 'open':
        flash('Cannot edit a resolved case')
        return redirect(url_for('cases.view_case', case_id=case_id))

    form = EditCaseForm(obj=case)
    form.case_type.choices = [('', 'Select a type')] + [(t.name, t.name) for t in CaseType.query.filter_by(hidden=False).order_by(CaseType.sort_order).all()]
    form.category.choices = [('', 'Select a category')] + [(c.name, c.name) for c in CaseCategory.query.filter_by(hidden=False).order_by(CaseCategory.sort_order).all()]
    if current_user.is_staff:
        states = CaseState.query.filter_by(hidden=False).order_by(CaseState.sort_order).all()
        form.state_id.choices = [(s.id, s.name) for s in states]
    else:
        del form.state_id

    if form.validate_on_submit():
        case.title = form.title.data
        case.description = form.description.data
        case.case_type = form.case_type.data
        case.category = form.category.data
        case.submitted_for = form.submitted_for.data
        if current_user.is_staff:
            case.state_id = form.state_id.data if form.state_id.data else None
        db.session.commit()
        flash('Case updated successfully')
        return redirect(url_for('cases.view_case', case_id=case_id))

    if current_user.is_staff:
        form.state_id.data = case.state_id
    return render_template('edit_case.html', form=form, case=case)


@cases_bp.route('/case/<int:case_id>')
@login_required
def view_case(case_id):
    case = Case.query.get_or_404(case_id)
    if not current_user.is_staff and case.user_id != current_user.id:
        flash('Access denied')
        return redirect(url_for('cases.dashboard'))

    comment_form = CommentForm()
    assign_form = AssignForm()

    if current_user.is_staff and (current_user.is_admin or case.assignment_group_id in user_group_ids(current_user)):
        if current_user.is_admin:
            group_users = User.query.filter_by(is_staff=True).order_by(User.username).all()
        else:
            group_ids = user_group_ids(current_user)
            group_users = User.query.filter(
                User.is_staff == True,
                User.groups.any(Group.id.in_(group_ids))
            ).order_by(User.username).all()
        assign_form.assigned_to.choices = [
            (u.id, u.username) for u in group_users
        ]
    else:
        assign_form.assigned_to.choices = []

    all_groups = Group.query.order_by(Group.name).all() if current_user.is_admin else []

    return render_template('view_case.html', case=case,
                           comment_form=comment_form,
                           assign_form=assign_form,
                           all_groups=all_groups)


@cases_bp.route('/case/<int:case_id>/comment', methods=['POST'])
@login_required
def add_comment(case_id):
    case = Case.query.get_or_404(case_id)
    if not current_user.is_staff and case.user_id != current_user.id:
        flash('Access denied')
        return redirect(url_for('cases.dashboard'))
    form = CommentForm()
    if form.validate_on_submit():
        comment = Comment(
            content=form.content.data,
            user_id=current_user.id,
            case_id=case_id,
        )
        db.session.add(comment)
        db.session.commit()
        flash('Comment added successfully')
    return redirect(url_for('cases.view_case', case_id=case_id))


@cases_bp.route('/case/<int:case_id>/assign', methods=['POST'])
@login_required
def assign_case(case_id):
    if not current_user.is_staff:
        flash('Access denied')
        return redirect(url_for('cases.dashboard'))
    case = Case.query.get_or_404(case_id)
    form = AssignForm()
    if current_user.is_admin:
        group_users = User.query.filter_by(is_staff=True).order_by(User.username).all()
    else:
        group_ids = user_group_ids(current_user)
        group_users = User.query.filter(
            User.is_staff == True,
            User.groups.any(Group.id.in_(group_ids))
        ).all()
    form.assigned_to.choices = [(u.id, u.username) for u in group_users]
    if form.validate_on_submit():
        user = User.query.get(form.assigned_to.data)
        if user:
            if current_user.is_admin:
                case.assigned_to_id = user.id
                db.session.commit()
                flash('Case assigned successfully')
            else:
                user_group_ids_set = set(g.id for g in user.groups)
                if set(group_ids) & user_group_ids_set:
                    case.assigned_to_id = user.id
                    db.session.commit()
                    flash('Case assigned successfully')
                else:
                    flash('Invalid assignment')
        else:
            flash('Invalid assignment')
    return redirect(url_for('cases.dashboard'))


@cases_bp.route('/case/<int:case_id>/resolve', methods=['POST'])
@login_required
def resolve_case(case_id):
    case = Case.query.get_or_404(case_id)
    if not current_user.is_staff:
        flash('Access denied')
        return redirect(url_for('cases.dashboard'))
    if case.assigned_to_id != current_user.id:
        flash('Only the assigned staff member can resolve this case')
        return redirect(url_for('cases.view_case', case_id=case_id))
    case.resolved_date = datetime.utcnow()
    case.status = 'resolved'
    db.session.commit()
    flash('Case resolved successfully')
    return redirect(url_for('cases.dashboard'))


@cases_bp.route('/case/<int:case_id>/take', methods=['POST'])
@login_required
def take_case(case_id):
    case = Case.query.get_or_404(case_id)
    if not current_user.is_staff:
        flash('Access denied')
        return redirect(url_for('cases.dashboard'))
    if not current_user.is_admin and case.assignment_group_id not in user_group_ids(current_user):
        flash('You are not a member of this case\'s group')
        return redirect(url_for('cases.view_case', case_id=case_id))
    if case.status != 'open':
        flash('Only open cases can be assigned')
        return redirect(url_for('cases.view_case', case_id=case_id))
    case.assigned_to_id = current_user.id
    db.session.commit()
    flash('You have taken ownership of this case')
    return redirect(url_for('cases.view_case', case_id=case_id))


@cases_bp.route('/case/<int:case_id>/transfer', methods=['POST'])
@login_required
def transfer_case(case_id):
    case = Case.query.get_or_404(case_id)
    if not current_user.is_staff:
        flash('Access denied')
        return redirect(url_for('cases.dashboard'))
    group_id = request.form.get('group_id', type=int)
    if not group_id:
        flash('No group selected')
        return redirect(url_for('cases.view_case', case_id=case_id))
    target_group = Group.query.get(group_id)
    if not target_group:
        flash('Invalid group')
        return redirect(url_for('cases.view_case', case_id=case_id))
    if not current_user.is_admin and target_group not in current_user.groups:
        flash('You can only transfer cases to groups you belong to')
        return redirect(url_for('cases.view_case', case_id=case_id))
    if not current_user.is_admin and case.assignment_group_id not in user_group_ids(current_user):
        flash('You are not a member of this case\'s current group')
        return redirect(url_for('cases.view_case', case_id=case_id))
    case.assignment_group_id = group_id
    case.assigned_to_id = None
    db.session.commit()
    flash(f'Case transferred to {target_group.name}')
    return redirect(url_for('cases.view_case', case_id=case_id))


@cases_bp.route('/upload_attachment/<int:case_id>', methods=['POST'])
@login_required
def upload_attachment(case_id):
    case = Case.query.get_or_404(case_id)
    if not current_user.is_staff and case.user_id != current_user.id:
        flash('Access denied')
        return redirect(url_for('cases.dashboard'))
    if 'file' not in request.files:
        flash('No file selected')
        return redirect(url_for('cases.view_case', case_id=case_id))
    file = request.files['file']
    if file.filename == '':
        flash('No file selected')
        return redirect(url_for('cases.view_case', case_id=case_id))
    if not allowed_file(file.filename):
        flash('File type not allowed')
        return redirect(url_for('cases.view_case', case_id=case_id))
    if file:
        original_filename = secure_filename(file.filename)
        unique_filename = str(uuid.uuid4()) + '_' + original_filename
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(filepath)
        attachment = Attachment(
            filename=original_filename,
            filepath=filepath,
            case_id=case_id,
        )
        db.session.add(attachment)
        db.session.commit()
        flash('File uploaded successfully')
    return redirect(url_for('cases.view_case', case_id=case_id))


@cases_bp.route('/download/<int:attachment_id>')
@login_required
def download_attachment(attachment_id):
    attachment = Attachment.query.get_or_404(attachment_id)
    case = Case.query.get_or_404(attachment.case_id)
    if not current_user.is_staff and case.user_id != current_user.id:
        flash('Access denied')
        return redirect(url_for('cases.dashboard'))
    return send_file(attachment.filepath, as_attachment=True,
                     download_name=attachment.filename)


@cases_bp.route('/api/cases')
@login_required
def api_cases():
    if current_user.is_staff:
        group_ids = user_group_ids(current_user)
        cases = Case.query.filter(Case.assignment_group_id.in_(group_ids)).all() if group_ids else []
    else:
        cases = Case.query.filter_by(user_id=current_user.id).all()
    return jsonify([{
        'id': case.id,
        'title': case.title,
        'description': case.description,
        'created_date': case.created_date.isoformat(),
        'status': case.status,
        'assigned_to': case.assigned_to.username if case.assigned_to else None,
    } for case in cases])
