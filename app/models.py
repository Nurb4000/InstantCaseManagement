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
    managed_group = db.relationship('Group', back_populates='manager', lazy='select', uselist=False, foreign_keys='Group.manager_id')
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
    hidden = db.Column(db.Boolean, default=False)
    business_hours_start = db.Column(db.Integer, default=6)
    business_hours_end = db.Column(db.Integer, default=18)
    business_hours_days = db.Column(db.String(100), default='Mon,Tue,Wed,Thu,Fri')
    manager_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    ola_hours = db.Column(db.Float, default=2.0)
    users = db.relationship('User', secondary=user_groups, back_populates='groups', lazy='select')
    manager = db.relationship('User', foreign_keys=[manager_id], back_populates='managed_group', lazy='joined')

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
    sla_hours = db.Column(db.Float, default=0)

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
    ola_started_at = db.Column(db.DateTime, nullable=True)
    ola_group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=True)
    sla_started_at = db.Column(db.DateTime, nullable=True)
    sla_paused_at = db.Column(db.DateTime, nullable=True)
    sla_total_paused_seconds = db.Column(db.Integer, default=0)
    ola_status = db.Column(db.String(20), nullable=True)
    sla_status = db.Column(db.String(20), nullable=True)

    state = db.relationship('CaseState', foreign_keys=[state_id])
    assignment_group = db.relationship('Group', foreign_keys=[assignment_group_id])
    assigned_to = db.relationship('User', foreign_keys=[assigned_to_id], back_populates='assigned_cases')
    user = db.relationship('User', back_populates='cases', foreign_keys=[user_id])
    comments = db.relationship('Comment', backref='case', lazy=True, cascade='all, delete-orphan')
    attachments = db.relationship('Attachment', backref='case', lazy=True, cascade='all, delete-orphan')
    ola_events = db.relationship('OLAEvent', backref='case', lazy=True, cascade='all, delete-orphan',
                                 order_by='OLAEvent.timestamp')
    sla_events = db.relationship('SLAEvent', backref='case', lazy=True, cascade='all, delete-orphan',
                                 order_by='SLAEvent.timestamp')


class OLAEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey('case.id'), nullable=False)
    event_type = db.Column(db.String(50), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=True)
    group_name = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    details = db.Column(db.Text, nullable=True)


class SLAEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey('case.id'), nullable=False)
    event_type = db.Column(db.String(50), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    details = db.Column(db.Text, nullable=True)


class OrgSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_hours_start = db.Column(db.Integer, default=6)
    business_hours_end = db.Column(db.Integer, default=18)
    business_hours_days = db.Column(db.String(100), default='Mon,Tue,Wed,Thu,Fri')
    smtp_server = db.Column(db.String(200), default='')
    smtp_port = db.Column(db.Integer, default=587)
    smtp_username = db.Column(db.String(200), default='')
    smtp_password = db.Column(db.String(200), default='')
    smtp_from_email = db.Column(db.String(200), default='')
    smtp_use_tls = db.Column(db.Boolean, default=True)

    @classmethod
    def get(cls):
        setting = cls.query.get(1)
        if not setting:
            setting = cls(id=1)
            db.session.add(setting)
            db.session.commit()
        return setting


class EmailLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey('case.id'), nullable=True)
    recipient = db.Column(db.String(200), nullable=False)
    subject = db.Column(db.String(300), nullable=False)
    body = db.Column(db.Text, nullable=False)
    sent_date = db.Column(db.DateTime, default=datetime.utcnow)
    direction = db.Column(db.String(20), default='outgoing')

    case = db.relationship('Case', backref='email_logs', lazy=True)


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
