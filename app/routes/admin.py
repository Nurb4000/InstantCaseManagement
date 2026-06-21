from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app import db
from app.models import User, Group, Case, CaseState, CaseType, CaseCategory, OrgSetting
from app.forms import GroupForm, UserGroupForm, CaseStateForm, AdminPasswordResetForm, CaseTypeForm, CaseCategoryForm, AdminEditUserForm, AdminCreateUserForm, OrgSettingsForm

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Access denied')
            return redirect(url_for('cases.dashboard'))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route('/groups')
@login_required
@admin_required
def list_groups():
    groups = Group.query.all()
    return render_template('admin/groups.html', groups=groups)


@admin_bp.route('/groups/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_group():
    form = GroupForm()
    staff_users = User.query.filter_by(is_staff=True).order_by(User.username).all()
    form.manager_id.choices = [(0, '— No manager —')] + [(u.id, u.username) for u in staff_users]
    if not form.is_submitted():
        form.business_hours_days.data = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
        form.manager_id.data = 0
    if form.validate_on_submit():
        existing = Group.query.filter_by(name=form.name.data).first()
        if existing:
            flash('A group with that name already exists')
            return render_template('admin/group_form.html', form=form, title='Create Group')
        group = Group(
            name=form.name.data,
            description=form.description.data,
            hidden=form.hidden.data,
            business_hours_start=form.business_hours_start.data,
            business_hours_end=form.business_hours_end.data,
            business_hours_days=','.join(form.business_hours_days.data),
            manager_id=form.manager_id.data if form.manager_id.data else None,
            ola_hours=form.ola_hours.data if form.ola_hours.data else 2.0
        )
        db.session.add(group)
        db.session.commit()
        flash(f'Group "{group.name}" created')
        return redirect(url_for('admin.list_groups'))
    return render_template('admin/group_form.html', form=form, title='Create Group')


@admin_bp.route('/groups/<int:group_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_group(group_id):
    group = Group.query.get_or_404(group_id)
    form = GroupForm(obj=group)
    staff_users = User.query.filter_by(is_staff=True).order_by(User.username).all()
    form.manager_id.choices = [(0, '— No manager —')] + [(u.id, u.username) for u in staff_users]
    if not form.is_submitted():
        form.business_hours_days.data = group.business_hours_days.split(',') if group.business_hours_days else []
        form.manager_id.data = group.manager_id or 0
    if form.validate_on_submit():
        duplicate = Group.query.filter(
            Group.name == form.name.data, Group.id != group_id
        ).first()
        if duplicate:
            flash('A group with that name already exists')
            return render_template('admin/group_form.html', form=form, title='Edit Group', group=group)
        group.name = form.name.data
        group.description = form.description.data
        group.hidden = form.hidden.data
        group.business_hours_start = form.business_hours_start.data
        group.business_hours_end = form.business_hours_end.data
        group.business_hours_days = ','.join(form.business_hours_days.data)
        group.manager_id = form.manager_id.data if form.manager_id.data else None
        group.ola_hours = form.ola_hours.data if form.ola_hours.data else 2.0
        db.session.commit()
        flash('Group updated')
        return redirect(url_for('admin.list_groups'))
    return render_template('admin/group_form.html', form=form, title='Edit Group', group=group)


@admin_bp.route('/groups/<int:group_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_group(group_id):
    group = Group.query.get_or_404(group_id)
    if group.users:
        flash('Cannot delete a group that has members. Remove all members first.')
        return redirect(url_for('admin.view_group', group_id=group_id))
    db.session.delete(group)
    db.session.commit()
    flash('Group deleted')
    return redirect(url_for('admin.list_groups'))


@admin_bp.route('/groups/<int:group_id>')
@login_required
@admin_required
def view_group(group_id):
    group = Group.query.get_or_404(group_id)
    form = UserGroupForm()
    available_users = User.query.filter(
        ~User.groups.any(Group.id == group_id)
    ).order_by(User.username).all()
    form.user_id.choices = [(u.id, f'{u.username} ({u.email})') for u in available_users]
    return render_template('admin/group_detail.html', group=group, form=form)


@admin_bp.route('/groups/<int:group_id>/users/add', methods=['POST'])
@login_required
@admin_required
def add_user_to_group(group_id):
    group = Group.query.get_or_404(group_id)
    form = UserGroupForm()
    available_users = User.query.filter(
        ~User.groups.any(Group.id == group_id)
    ).order_by(User.username).all()
    form.user_id.choices = [(u.id, u.username) for u in available_users]
    if form.validate_on_submit():
        user = User.query.get(form.user_id.data)
        if user and user not in group.users:
            group.users.append(user)
            db.session.commit()
            flash(f'Added {user.username} to {group.name}')
    return redirect(url_for('admin.view_group', group_id=group_id))


@admin_bp.route('/groups/<int:group_id>/users/<int:user_id>/remove', methods=['POST'])
@login_required
@admin_required
def remove_user_from_group(group_id, user_id):
    group = Group.query.get_or_404(group_id)
    user = User.query.get_or_404(user_id)
    if user in group.users:
        group.users.remove(user)
        db.session.commit()
        flash(f'Removed {user.username} from {group.name}')
    return redirect(url_for('admin.view_group', group_id=group_id))


@admin_bp.route('/groups/<int:group_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_group(group_id):
    group = Group.query.get_or_404(group_id)
    group.hidden = not group.hidden
    db.session.commit()
    status = 'hidden' if group.hidden else 'visible'
    flash(f'Group "{group.name}" is now {status}')
    return redirect(url_for('admin.list_groups'))


@admin_bp.route('/users')
@login_required
@admin_required
def list_users():
    users = User.query.order_by(User.username).all()
    return render_template('admin/users.html', users=users)


@admin_bp.route('/users/<int:user_id>/toggle-staff', methods=['POST'])
@login_required
@admin_required
def toggle_staff(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot change your own staff status')
        return redirect(url_for('admin.list_users'))
    user.is_staff = not user.is_staff
    db.session.commit()
    status = 'granted' if user.is_staff else 'removed'
    flash(f'Staff access {status} for {user.username}')
    return redirect(url_for('admin.list_users'))


@admin_bp.route('/users/<int:user_id>/toggle-admin', methods=['POST'])
@login_required
@admin_required
def toggle_admin(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot change your own admin status')
        return redirect(url_for('admin.list_users'))
    user.is_admin = not user.is_admin
    db.session.commit()
    status = 'granted' if user.is_admin else 'removed'
    flash(f'Admin access {status} for {user.username}')
    return redirect(url_for('admin.list_users'))


@admin_bp.route('/users/<int:user_id>')
@login_required
@admin_required
def view_user(user_id):
    user = User.query.get_or_404(user_id)
    all_groups = Group.query.order_by(Group.name).all()
    return render_template('admin/user_detail.html', user=user, all_groups=all_groups)


@admin_bp.route('/users/<int:user_id>/reset-password', methods=['GET', 'POST'])
@login_required
@admin_required
def reset_password(user_id):
    user = User.query.get_or_404(user_id)
    form = AdminPasswordResetForm()
    if form.validate_on_submit():
        user.set_password(form.new_password.data)
        db.session.commit()
        flash(f'Password reset for {user.username}')
        return redirect(url_for('admin.view_user', user_id=user_id))
    return render_template('admin/reset_password.html', form=form, user=user)


@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    form = AdminEditUserForm(obj=user)
    if form.validate_on_submit():
        if form.username.data != user.username and User.query.filter_by(username=form.username.data).first():
            flash('Username already taken')
            return render_template('admin/edit_user.html', form=form, user=user)
        if form.email.data != user.email and User.query.filter_by(email=form.email.data).first():
            flash('Email already taken')
            return render_template('admin/edit_user.html', form=form, user=user)
        user.username = form.username.data
        user.email = form.email.data
        db.session.commit()
        flash('User updated')
        return redirect(url_for('admin.view_user', user_id=user_id))
    return render_template('admin/edit_user.html', form=form, user=user)


@admin_bp.route('/users/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_user():
    form = AdminCreateUserForm()
    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data).first():
            flash('Username already taken')
            return render_template('admin/create_user.html', form=form)
        if User.query.filter_by(email=form.email.data).first():
            flash('Email already taken')
            return render_template('admin/create_user.html', form=form)
        user = User(
            username=form.username.data,
            email=form.email.data,
            is_staff=form.is_staff.data,
            is_admin=form.is_admin.data
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash(f'User "{user.username}" created')
        return redirect(url_for('admin.list_users'))
    return render_template('admin/create_user.html', form=form)


@admin_bp.route('/users/<int:user_id>/groups/<int:group_id>/add', methods=['POST'])
@login_required
@admin_required
def add_group_to_user(user_id, group_id):
    user = User.query.get_or_404(user_id)
    group = Group.query.get_or_404(group_id)
    if group not in user.groups:
        user.groups.append(group)
        db.session.commit()
        flash(f'Added {user.username} to {group.name}')
    return redirect(url_for('admin.view_user', user_id=user_id))


@admin_bp.route('/users/<int:user_id>/groups/<int:group_id>/remove', methods=['POST'])
@login_required
@admin_required
def remove_group_from_user(user_id, group_id):
    user = User.query.get_or_404(user_id)
    group = Group.query.get_or_404(group_id)
    if group in user.groups:
        user.groups.remove(group)
        db.session.commit()
        flash(f'Removed {user.username} from {group.name}')
    return redirect(url_for('admin.view_user', user_id=user_id))


@admin_bp.route('/cases')
@login_required
@admin_required
def all_cases():
    return redirect(url_for('cases.all_cases'))


@admin_bp.route('/states')
@login_required
@admin_required
def list_states():
    states = CaseState.query.order_by(CaseState.sort_order).all()
    return render_template('admin/states.html', states=states)


@admin_bp.route('/states/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_state():
    form = CaseStateForm()
    if form.validate_on_submit():
        existing = CaseState.query.filter_by(name=form.name.data).first()
        if existing:
            flash('A state with that name already exists')
            return render_template('admin/state_form.html', form=form, title='Create State')
        state = CaseState(name=form.name.data, sort_order=form.sort_order.data)
        db.session.add(state)
        db.session.commit()
        flash(f'State "{state.name}" created')
        return redirect(url_for('admin.list_states'))
    return render_template('admin/state_form.html', form=form, title='Create State')


@admin_bp.route('/states/<int:state_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_state(state_id):
    state = CaseState.query.get_or_404(state_id)
    form = CaseStateForm(obj=state)
    if form.validate_on_submit():
        duplicate = CaseState.query.filter(
            CaseState.name == form.name.data, CaseState.id != state_id
        ).first()
        if duplicate:
            flash('A state with that name already exists')
            return render_template('admin/state_form.html', form=form, title='Edit State', state=state)
        state.name = form.name.data
        state.sort_order = form.sort_order.data
        db.session.commit()
        flash('State updated')
        return redirect(url_for('admin.list_states'))
    return render_template('admin/state_form.html', form=form, title='Edit State', state=state)


@admin_bp.route('/states/<int:state_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_state(state_id):
    state = CaseState.query.get_or_404(state_id)
    cases_using = Case.query.filter_by(state_id=state_id).count()
    if cases_using:
        flash(f'Cannot delete "{state.name}" — {cases_using} case(s) are using it')
        return redirect(url_for('admin.list_states'))
    db.session.delete(state)
    db.session.commit()
    flash('State deleted')
    return redirect(url_for('admin.list_states'))


@admin_bp.route('/states/<int:state_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_state(state_id):
    state = CaseState.query.get_or_404(state_id)
    state.hidden = not state.hidden
    db.session.commit()
    status = 'hidden' if state.hidden else 'visible'
    flash(f'State "{state.name}" is now {status}')
    return redirect(url_for('admin.list_states'))


# ---- Case Types ----

@admin_bp.route('/types')
@login_required
@admin_required
def list_types():
    types = CaseType.query.order_by(CaseType.sort_order).all()
    return render_template('admin/list_options.html',
                           title='Case Types', items=types,
                           create_url='admin.create_type',
                           edit_url='admin.edit_type',
                           delete_url='admin.delete_type',
                           label='type')


@admin_bp.route('/types/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_type():
    form = CaseTypeForm()
    if form.validate_on_submit():
        existing = CaseType.query.filter_by(name=form.name.data).first()
        if existing:
            flash('A type with that name already exists')
            return render_template('admin/option_form.html', form=form, title='Create Type', label='type')
        sla = 0
        if form.sla_hours.data:
            try:
                sla = float(form.sla_hours.data)
            except ValueError:
                pass
        item = CaseType(name=form.name.data, sort_order=form.sort_order.data, sla_hours=sla)
        db.session.add(item)
        db.session.commit()
        flash(f'Type "{item.name}" created')
        return redirect(url_for('admin.list_types'))
    return render_template('admin/option_form.html', form=form, title='Create Type', label='type')


@admin_bp.route('/types/<int:item_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_type(item_id):
    item = CaseType.query.get_or_404(item_id)
    form = CaseTypeForm(obj=item)
    if form.validate_on_submit():
        dup = CaseType.query.filter(CaseType.name == form.name.data, CaseType.id != item_id).first()
        if dup:
            flash('A type with that name already exists')
            return render_template('admin/option_form.html', form=form, title='Edit Type', label='type', item=item)
        item.name = form.name.data
        item.sort_order = form.sort_order.data
        sla = 0
        if form.sla_hours.data:
            try:
                sla = float(form.sla_hours.data)
            except ValueError:
                pass
        item.sla_hours = sla
        db.session.commit()
        flash('Type updated')
        return redirect(url_for('admin.list_types'))
    return render_template('admin/option_form.html', form=form, title='Edit Type', label='type', item=item)


@admin_bp.route('/types/<int:item_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_type(item_id):
    item = CaseType.query.get_or_404(item_id)
    in_use = Case.query.filter_by(case_type=item.name).count()
    if in_use:
        flash(f'Cannot delete "{item.name}" — {in_use} case(s) are using it')
        return redirect(url_for('admin.list_types'))
    db.session.delete(item)
    db.session.commit()
    flash('Type deleted')
    return redirect(url_for('admin.list_types'))


@admin_bp.route('/types/<int:item_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_type(item_id):
    item = CaseType.query.get_or_404(item_id)
    item.hidden = not item.hidden
    db.session.commit()
    status = 'hidden' if item.hidden else 'visible'
    flash(f'Type "{item.name}" is now {status}')
    return redirect(url_for('admin.list_types'))


# ---- Case Categories ----

@admin_bp.route('/categories')
@login_required
@admin_required
def list_categories():
    items = CaseCategory.query.order_by(CaseCategory.sort_order).all()
    return render_template('admin/list_options.html',
                           title='Case Categories', items=items,
                           create_url='admin.create_category',
                           edit_url='admin.edit_category',
                           delete_url='admin.delete_category',
                           label='category')


@admin_bp.route('/categories/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_category():
    form = CaseCategoryForm()
    if form.validate_on_submit():
        existing = CaseCategory.query.filter_by(name=form.name.data).first()
        if existing:
            flash('A category with that name already exists')
            return render_template('admin/option_form.html', form=form, title='Create Category', label='category')
        item = CaseCategory(name=form.name.data, sort_order=form.sort_order.data)
        db.session.add(item)
        db.session.commit()
        flash(f'Category "{item.name}" created')
        return redirect(url_for('admin.list_categories'))
    return render_template('admin/option_form.html', form=form, title='Create Category', label='category')


@admin_bp.route('/categories/<int:item_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_category(item_id):
    item = CaseCategory.query.get_or_404(item_id)
    form = CaseCategoryForm(obj=item)
    if form.validate_on_submit():
        dup = CaseCategory.query.filter(CaseCategory.name == form.name.data, CaseCategory.id != item_id).first()
        if dup:
            flash('A category with that name already exists')
            return render_template('admin/option_form.html', form=form, title='Edit Category', label='category', item=item)
        item.name = form.name.data
        item.sort_order = form.sort_order.data
        db.session.commit()
        flash('Category updated')
        return redirect(url_for('admin.list_categories'))
    return render_template('admin/option_form.html', form=form, title='Edit Category', label='category', item=item)


@admin_bp.route('/categories/<int:item_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_category(item_id):
    item = CaseCategory.query.get_or_404(item_id)
    in_use = Case.query.filter_by(category=item.name).count()
    if in_use:
        flash(f'Cannot delete "{item.name}" — {in_use} case(s) are using it')
        return redirect(url_for('admin.list_categories'))
    db.session.delete(item)
    db.session.commit()
    flash('Category deleted')
    return redirect(url_for('admin.list_categories'))


@admin_bp.route('/categories/<int:item_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_category(item_id):
    item = CaseCategory.query.get_or_404(item_id)
    item.hidden = not item.hidden
    db.session.commit()
    status = 'hidden' if item.hidden else 'visible'
    flash(f'Category "{item.name}" is now {status}')
    return redirect(url_for('admin.list_categories'))


# ---- Org Settings ----

@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def org_settings():
    org = OrgSetting.get()
    form = OrgSettingsForm(obj=org)
    if not form.is_submitted():
        form.business_hours_days.data = org.business_hours_days.split(',') if org.business_hours_days else []
    if form.validate_on_submit():
        org.business_hours_start = form.business_hours_start.data
        org.business_hours_end = form.business_hours_end.data
        org.business_hours_days = ','.join(form.business_hours_days.data)
        org.smtp_server = form.smtp_server.data or ''
        if form.smtp_port.data:
            try:
                org.smtp_port = int(form.smtp_port.data)
            except ValueError:
                pass
        org.smtp_username = form.smtp_username.data or ''
        if form.smtp_password.data:
            org.smtp_password = form.smtp_password.data
        org.smtp_from_email = form.smtp_from_email.data or ''
        org.smtp_use_tls = form.smtp_use_tls.data
        db.session.commit()
        flash('Organization settings updated')
        return redirect(url_for('admin.org_settings'))
    return render_template('admin/settings.html', form=form)
