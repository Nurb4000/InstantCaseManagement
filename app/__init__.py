import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
limiter = Limiter(key_func=get_remote_address)
csrf = CSRFProtect()


def create_app(testing=False):
    app = Flask(__name__, template_folder='../templates')
    app.config['SECRET_KEY'] = os.environ.get(
        'SECRET_KEY', os.urandom(64).hex()
    )
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'DATABASE_URL', 'sqlite:///instant_call_center.db'
    )
    app.config['UPLOAD_FOLDER'] = os.environ.get(
        'UPLOAD_FOLDER', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'uploads')
    )
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
    app.config['WTF_CSRF_ENABLED'] = True
    app.config['TESTING'] = testing

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    migrate.init_app(app, db)
    limiter.init_app(app)
    csrf.init_app(app)

    from app.routes.auth import auth_bp
    from app.routes.cases import cases_bp
    from app.routes.admin import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(admin_bp)

    @app.template_filter('local_fmt')
    def to_local_fmt(dt, fmt='%Y-%m-%d %H:%M'):
        if dt is None:
            return ''
        from datetime import timezone
        utc_dt = dt.replace(tzinfo=timezone.utc)
        local_dt = utc_dt.astimezone()
        return local_dt.strftime(fmt)

    with app.app_context():
        from app.models import Group, User, CaseState, CaseType, CaseCategory, Case, OLAEvent
        db.create_all()

        # Migrate existing database: add new columns if missing
        import sqlalchemy as sa
        inspector = sa.inspect(db.engine)

        # Group table migration
        group_columns = [c['name'] for c in inspector.get_columns('group')]
        if 'hidden' not in group_columns:
            db.session.execute(sa.text('ALTER TABLE "group" ADD COLUMN hidden BOOLEAN DEFAULT 0'))
        if 'business_hours_start' not in group_columns:
            db.session.execute(sa.text('ALTER TABLE "group" ADD COLUMN business_hours_start INTEGER DEFAULT 6'))
        if 'business_hours_end' not in group_columns:
            db.session.execute(sa.text('ALTER TABLE "group" ADD COLUMN business_hours_end INTEGER DEFAULT 18'))
        if 'business_hours_days' not in group_columns:
            db.session.execute(sa.text('ALTER TABLE "group" ADD COLUMN business_hours_days VARCHAR(100) DEFAULT "Mon,Tue,Wed,Thu,Fri"'))
        if 'manager_id' not in group_columns:
            db.session.execute(sa.text('ALTER TABLE "group" ADD COLUMN manager_id INTEGER REFERENCES user(id)'))
        if 'ola_hours' not in group_columns:
            db.session.execute(sa.text('ALTER TABLE "group" ADD COLUMN ola_hours FLOAT DEFAULT 2.0'))

        # Case table migration
        case_columns = [c['name'] for c in inspector.get_columns('case')]
        if 'ola_started_at' not in case_columns:
            db.session.execute(sa.text('ALTER TABLE "case" ADD COLUMN ola_started_at DATETIME'))
        if 'ola_group_id' not in case_columns:
            db.session.execute(sa.text('ALTER TABLE "case" ADD COLUMN ola_group_id INTEGER REFERENCES "group"(id)'))
        if 'sla_started_at' not in case_columns:
            db.session.execute(sa.text('ALTER TABLE "case" ADD COLUMN sla_started_at DATETIME'))
        if 'sla_paused_at' not in case_columns:
            db.session.execute(sa.text('ALTER TABLE "case" ADD COLUMN sla_paused_at DATETIME'))
        if 'sla_total_paused_seconds' not in case_columns:
            db.session.execute(sa.text('ALTER TABLE "case" ADD COLUMN sla_total_paused_seconds INTEGER DEFAULT 0'))
        if 'ola_status' not in case_columns:
            db.session.execute(sa.text('ALTER TABLE "case" ADD COLUMN ola_status VARCHAR(20)'))
        if 'sla_status' not in case_columns:
            db.session.execute(sa.text('ALTER TABLE "case" ADD COLUMN sla_status VARCHAR(20)'))

        # CaseType table migration
        ct_columns = [c['name'] for c in inspector.get_columns('case_type')]
        if 'sla_hours' not in ct_columns:
            db.session.execute(sa.text('ALTER TABLE "case_type" ADD COLUMN sla_hours FLOAT DEFAULT 0'))

        # OrgSetting table migration
        os_columns = [c['name'] for c in inspector.get_columns('org_setting')]
        if 'smtp_server' not in os_columns:
            db.session.execute(sa.text('ALTER TABLE "org_setting" ADD COLUMN smtp_server VARCHAR(200) DEFAULT ""'))
        if 'smtp_port' not in os_columns:
            db.session.execute(sa.text('ALTER TABLE "org_setting" ADD COLUMN smtp_port INTEGER DEFAULT 587'))
        if 'smtp_username' not in os_columns:
            db.session.execute(sa.text('ALTER TABLE "org_setting" ADD COLUMN smtp_username VARCHAR(200) DEFAULT ""'))
        if 'smtp_password' not in os_columns:
            db.session.execute(sa.text('ALTER TABLE "org_setting" ADD COLUMN smtp_password VARCHAR(200) DEFAULT ""'))
        if 'smtp_from_email' not in os_columns:
            db.session.execute(sa.text('ALTER TABLE "org_setting" ADD COLUMN smtp_from_email VARCHAR(200) DEFAULT ""'))
        if 'smtp_use_tls' not in os_columns:
            db.session.execute(sa.text('ALTER TABLE "org_setting" ADD COLUMN smtp_use_tls BOOLEAN DEFAULT 1'))

        db.session.commit()

        # Ensure OrgSetting exists
        from app.models import OrgSetting
        if not OrgSetting.query.get(1):
            db.session.add(OrgSetting(id=1))
            db.session.commit()

        default_states = [
            ('New', 0),
            ('In Progress', 1),
            ('On Hold', 2),
            ('Waiting on Customer', 3),
            ('Waiting on Vendor', 4),
            ('Waiting on Resolution Approval', 5),
        ]
        for name, order in default_states:
            if not CaseState.query.filter_by(name=name).first():
                db.session.add(CaseState(name=name, sort_order=order))

        default_types = ['Technical', 'Billing', 'Account', 'Feature Request', 'Other']
        for i, name in enumerate(default_types):
            if not CaseType.query.filter_by(name=name).first():
                db.session.add(CaseType(name=name, sort_order=i))

        default_categories = ['Hardware', 'Software', 'Network', 'Security', 'Performance', 'Other']
        for i, name in enumerate(default_categories):
            if not CaseCategory.query.filter_by(name=name).first():
                db.session.add(CaseCategory(name=name, sort_order=i))

        db.session.commit()

        if os.environ.get('ADMIN_CREATE', '').lower() in ('1', 'true', 'yes'):
            if not Group.query.filter_by(name='Triage').first():
                triage_group = Group(name='Triage', description='Initial case handling group')
                db.session.add(triage_group)
                db.session.commit()
            else:
                triage_group = Group.query.filter_by(name='Triage').first()

            if not User.query.filter_by(username='admin').first():
                admin_user = User(username='admin', email='admin@example.com',
                                  is_staff=True, is_admin=True)
                admin_user.set_password(os.environ.get('ADMIN_PASSWORD', 'changeme123'))
                admin_user.groups.append(triage_group)
                db.session.add(admin_user)
                db.session.commit()

    if not testing:
        from apscheduler.schedulers.background import BackgroundScheduler
        from app.scheduler import run_ola_sla_update
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            func=run_ola_sla_update,
            trigger='interval',
            minutes=1,
            args=[app],
            id='ola_sla_updater',
            replace_existing=True,
        )
        scheduler.start()

    return app
