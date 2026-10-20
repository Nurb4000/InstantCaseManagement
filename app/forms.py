import re
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, SelectField, BooleanField, SelectMultipleField, FloatField
from wtforms.validators import DataRequired, Email, Length, ValidationError, Optional

# Obvious/common passwords that must never be accepted, regardless of complexity.
WEAK_PASSWORDS = {
    'changeme', 'changeme123', 'password', 'passw0rd', 'admin', 'administrator',
    '123456', '12345678', '123456789', '1234567890', 'qwerty', 'abc123',
    'letmein', 'welcome', 'monkey', 'dragon', 'iloveyou', 'sunshine',
    'princess', 'football', 'baseball', 'master', 'shadow', 'trustno1',
}

MIN_PASSWORD_LENGTH = 12


def _check_password_strength(password):
    """Return a list of human-readable problems (empty list means the password is strong)."""
    problems = []
    pw = password or ''
    if len(pw) < MIN_PASSWORD_LENGTH:
        problems.append('Password must be at least 12 characters long.')
    if not re.search(r'[a-z]', pw):
        problems.append('Password must contain a lowercase letter.')
    if not re.search(r'[A-Z]', pw):
        problems.append('Password must contain an uppercase letter.')
    if not re.search(r'[0-9]', pw):
        problems.append('Password must contain a number.')
    if not re.search(r'[^A-Za-z0-9]', pw):
        problems.append('Password must contain a special character.')
    if pw.lower() in WEAK_PASSWORDS:
        problems.append('This password is too common and cannot be used.')
    return problems


def password_is_strong(password):
    """Programmatic strength check (used by non-form code paths, e.g. admin bootstrap)."""
    return not _check_password_strength(password)


def password_complexity(form, field):
    problems = _check_password_strength(field.data)
    if problems:
        raise ValidationError(problems[0])


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    # Optional progressive-CAPTCHA field; only rendered/validated when the S4
    # guard has surfaced a challenge for the request's IP.
    captcha = StringField('CAPTCHA', validators=[Optional()])


class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[
        DataRequired(), Length(min=3, max=80)
    ])
    email = StringField('Email', validators=[
        DataRequired(), Email()
    ])
    password = PasswordField('Password', validators=[
        DataRequired(), password_complexity
    ])


class CaseForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(max=200)])
    description = TextAreaField('Description', validators=[DataRequired()])
    case_type = SelectField('Case Type', validators=[DataRequired()])
    category = SelectField('Category', validators=[DataRequired()])
    state_id = SelectField('State', coerce=int, validators=[Optional()])
    submitted_for = StringField('Submitted For', validators=[Optional(), Length(max=200)])
    # F4: optional triage priority; defaulted to P3 in the submit route.
    priority = SelectField('Priority', coerce=str, validators=[Optional()], choices=[])


class EditCaseForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(max=200)])
    description = TextAreaField('Description', validators=[DataRequired()])
    case_type = SelectField('Case Type', validators=[DataRequired()])
    category = SelectField('Category', validators=[DataRequired()])
    state_id = SelectField('State', coerce=int, validators=[Optional()])
    submitted_for = StringField('Submitted For', validators=[Optional(), Length(max=200)])
    state_change_reason = TextAreaField('Reason for State Change', validators=[Optional()])
    # F4: allow re-prioritising a case during editing.
    priority = SelectField('Priority', coerce=str, validators=[Optional()], choices=[])


class CommentForm(FlaskForm):
    content = TextAreaField('Content', validators=[DataRequired()])


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('Current Password', validators=[DataRequired()])
    new_password = PasswordField('New Password', validators=[DataRequired(), password_complexity])
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired()])

    def validate_confirm_password(form, field):
        if field.data != form.new_password.data:
            raise ValidationError('Passwords do not match.')


class AssignForm(FlaskForm):
    assigned_to = SelectField('Assign To', coerce=int, validators=[DataRequired()])


class GroupForm(FlaskForm):
    name = StringField('Group Name', validators=[DataRequired(), Length(max=100)])
    description = TextAreaField('Description', validators=[Optional()])
    hidden = BooleanField('Hidden')
    business_hours_start = SelectField('Business Hours Start', coerce=int, choices=[(i, f'{i:02d}:00') for i in range(24)])
    business_hours_end = SelectField('Business Hours End', coerce=int, choices=[(i, f'{i:02d}:00') for i in range(24)])
    business_hours_days = SelectMultipleField('Business Days', coerce=str, choices=[
        ('Mon', 'Monday'), ('Tue', 'Tuesday'), ('Wed', 'Wednesday'),
        ('Thu', 'Thursday'), ('Fri', 'Friday'), ('Sat', 'Saturday'), ('Sun', 'Sunday')
    ])
    manager_id = SelectField('Manager', coerce=int, validators=[Optional()])
    ola_hours = FloatField('OLA Target (hours)', validators=[Optional()], default=2.0)


class UserGroupForm(FlaskForm):
    user_id = SelectField('User', coerce=int, validators=[DataRequired()])


class AdminPasswordResetForm(FlaskForm):
    new_password = PasswordField('New Password', validators=[DataRequired(), password_complexity])
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired()])

    def validate_confirm_password(form, field):
        if field.data != form.new_password.data:
            raise ValidationError('Passwords do not match.')


class CaseStateForm(FlaskForm):
    name = StringField('State Name', validators=[DataRequired(), Length(max=100)])
    sort_order = SelectField('Sort Order', coerce=int, choices=[(i, str(i)) for i in range(1, 21)])


class CaseTypeForm(FlaskForm):
    name = StringField('Type Name', validators=[DataRequired(), Length(max=100)])
    sort_order = SelectField('Sort Order', coerce=int, choices=[(i, str(i)) for i in range(1, 21)])
    sla_hours = StringField('SLA Target (hours)', validators=[Optional()])


class CaseCategoryForm(FlaskForm):
    name = StringField('Category Name', validators=[DataRequired(), Length(max=100)])
    sort_order = SelectField('Sort Order', coerce=int, choices=[(i, str(i)) for i in range(1, 21)])


class AdminEditUserForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(max=80)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])


class OrgSettingsForm(FlaskForm):
    business_hours_start = SelectField('Business Hours Start', coerce=int, choices=[(i, f'{i:02d}:00') for i in range(24)])
    business_hours_end = SelectField('Business Hours End', coerce=int, choices=[(i, f'{i:02d}:00') for i in range(24)])
    business_hours_days = SelectMultipleField('Business Days', coerce=str, choices=[
        ('Mon', 'Monday'), ('Tue', 'Tuesday'), ('Wed', 'Wednesday'),
        ('Thu', 'Thursday'), ('Fri', 'Friday'), ('Sat', 'Saturday'), ('Sun', 'Sunday')
    ])
    smtp_server = StringField('SMTP Server', validators=[Optional()])
    smtp_port = StringField('SMTP Port', validators=[Optional()])
    smtp_username = StringField('SMTP Username', validators=[Optional()])
    smtp_password = PasswordField('SMTP Password', validators=[Optional()])
    smtp_from_email = StringField('From Email', validators=[Optional(), Email()])
    smtp_use_tls = BooleanField('Use TLS')


class AdminCreateUserForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField('Password', validators=[DataRequired(), password_complexity])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired()])
    is_staff = BooleanField('Staff Access')
    is_admin = BooleanField('Admin Access')

    def validate_confirm_password(form, field):
        if field.data != form.password.data:
            raise ValidationError('Passwords do not match.')
