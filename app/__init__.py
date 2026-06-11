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

    with app.app_context():
        from app.models import Group, User, CaseState, CaseType, CaseCategory
        db.create_all()

        default_states = [
            ('New', 0),
            ('In Progress', 1),
            ('On Hold', 2),
            ('Waiting on Customer', 3),
            ('Waiting on Vendor', 4),
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

    return app
