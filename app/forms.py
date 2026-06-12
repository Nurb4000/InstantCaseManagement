import re
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Email, Length, ValidationError, Optional


def password_complexity(form, field):
    password = field.data
    if len(password) < 8:
        raise ValidationError('Password must be at least 8 characters long.')
    if not re.search(r'[A-Za-z]', password):
        raise ValidationError('Password must contain at least one letter.')
    if not re.search(r'[0-9]', password):
        raise ValidationError('Password must contain at least one number.')


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])


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


class EditCaseForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(max=200)])
    description = TextAreaField('Description', validators=[DataRequired()])
    case_type = SelectField('Case Type', validators=[DataRequired()])
    category = SelectField('Category', validators=[DataRequired()])
    state_id = SelectField('State', coerce=int, validators=[Optional()])
    submitted_for = StringField('Submitted For', validators=[Optional(), Length(max=200)])


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


class CaseCategoryForm(FlaskForm):
    name = StringField('Category Name', validators=[DataRequired(), Length(max=100)])
    sort_order = SelectField('Sort Order', coerce=int, choices=[(i, str(i)) for i in range(1, 21)])


class AdminEditUserForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(max=80)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
