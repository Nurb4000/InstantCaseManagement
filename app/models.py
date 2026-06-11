from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db


user_groups = db.Table('user_groups',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('group.id'), primary_key=True)
)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_staff = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)

    groups = db.relationship('Group', secondary=user_groups, back_populates='users', lazy='select')
    cases = db.relationship('Case', back_populates='user', lazy=True, foreign_keys='Case.user_id')
    assigned_cases = db.relationship('Case', back_populates='assigned_to', lazy=True, foreign_keys='Case.assigned_to_id')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'


class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    users = db.relationship('User', secondary=user_groups, back_populates='groups', lazy='select')

    def __repr__(self):
        return f'<Group {self.name}>'


class CaseState(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    sort_order = db.Column(db.Integer, default=0)
    hidden = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<CaseState {self.name}>'


class CaseType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    sort_order = db.Column(db.Integer, default=0)
    hidden = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<CaseType {self.name}>'


class CaseCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    sort_order = db.Column(db.Integer, default=0)
    hidden = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<CaseCategory {self.name}>'


class Case(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    created_date = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_date = db.Column(db.DateTime)
    status = db.Column(db.String(50), default='open')
    case_type = db.Column(db.String(100))
    category = db.Column(db.String(100))
    state_id = db.Column(db.Integer, db.ForeignKey('case_state.id'), nullable=True)
    assignment_group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=True)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    submitted_for = db.Column(db.String(200), nullable=True)

    state = db.relationship('CaseState', foreign_keys=[state_id])
    assignment_group = db.relationship('Group', foreign_keys=[assignment_group_id])
    assigned_to = db.relationship('User', foreign_keys=[assigned_to_id], back_populates='assigned_cases')
    user = db.relationship('User', back_populates='cases', foreign_keys=[user_id])
    comments = db.relationship('Comment', backref='case', lazy=True, cascade='all, delete-orphan')
    attachments = db.relationship('Attachment', backref='case', lazy=True, cascade='all, delete-orphan')


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    case_id = db.Column(db.Integer, db.ForeignKey('case.id'), nullable=False)

    user = db.relationship('User')


class Attachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    filepath = db.Column(db.String(300), nullable=False)
    uploaded_date = db.Column(db.DateTime, default=datetime.utcnow)
    case_id = db.Column(db.Integer, db.ForeignKey('case.id'), nullable=False)
