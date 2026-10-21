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


# Placeholder / well-known-weak values that must never sign sessions in production.
_WEAK_SECRETS = {
    '', 'secret', 'changeme', 'changeme123', 'dev', 'development', 'test',
    'random', 'your-secret-key', 'replace-me', 'generate-a-random-secret-key-here',
    'please-change-me', 'change-me',
}


def _is_weak_secret(key):
    if not key or len(key) < 32:
        return True
    return key.lower() in _WEAK_SECRETS


def _is_flask_db_command():
    """True when running under ``flask db ...`` (init/migrate/upgrade/...)."""
    import sys
    return 'db' in sys.argv[1:]


def _initialize_database(app):
    """Q2: apply schema via Flask-Migrate instead of hand-rolled ALTER TABLE.

    - Fresh DB: ``upgrade()`` runs the initial migration and builds every table.
    - Legacy DB (built by the old create_all/ALTER path, no alembic history):
      ``upgrade()`` hits "table already exists"; we align alembic history to
      ``head`` so future migrations apply cleanly on the next start.
    """
    import sqlalchemy as sa
    from sqlalchemy.exc import OperationalError
    from flask_migrate import upgrade, stamp

    with app.app_context():
        inspector = sa.inspect(db.engine)
        has_version_table = 'alembic_version' in inspector.get_table_names()
        try:
            upgrade()
        except OperationalError as exc:
            if not has_version_table and 'exists' in str(exc).lower():
                # Legacy DB: tables already match current schema; align alembic
                # history to head so future migrations apply on the next start.
                stamp(revision='head')
            else:
                raise


def _seed_initial_data(app):
    from app.models import OrgSetting, CaseState, CaseType, CaseCategory, Group, User
    from app.forms import password_is_strong

    # Ensure OrgSetting exists
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

        if User.query.filter_by(username='admin').first():
            pass  # admin already exists; leave it alone
        elif password_is_strong(os.environ.get('ADMIN_PASSWORD', '')):
            # Operator supplied a strong password; create the admin with it.
            admin_user = User(
                username='admin', email='admin@example.com',
                is_staff=True, is_admin=True,
            )
            admin_user.set_password(os.environ.get('ADMIN_PASSWORD'))
            admin_user.groups.append(triage_group)
            db.session.add(admin_user)
            db.session.commit()
            app.logger.info("Admin account 'admin' created.")
        else:
            # S2: never bootstrap the admin with a weak/default password.
            # Refuse to create the account and fail loudly so the operator
            # knows to set a strong ADMIN_PASSWORD before first use.
            app.logger.error(
                "ADMIN_PASSWORD is missing or too weak (got %r). Refusing to "
                "create the admin account with a default password. Set a strong "
                "ADMIN_PASSWORD (>=12 chars, upper+lower+number+special, not a "
                "common password) in your environment and restart. Common "
                "passwords such as 'changeme123' are rejected.",
                os.environ.get('ADMIN_PASSWORD') or '(unset)',
            )


def create_app(testing=False):
    app = Flask(__name__, template_folder='../templates')
    # S1: fail closed if SECRET_KEY is missing or weak outside of tests.
    # Tests intentionally use short keys, so enforcement is skipped there.
    secret_key = os.environ.get('SECRET_KEY')
    if testing:
        app.config['SECRET_KEY'] = secret_key or os.urandom(64).hex()
    elif _is_weak_secret(secret_key):
        if os.environ.get('SECRET_KEY_ALLOW_WEAK'):
            app.config['SECRET_KEY'] = os.urandom(64).hex()
        else:
            raise RuntimeError(
                "SECRET_KEY is missing or weak. Export a strong SECRET_KEY "
                "(>= 32 random characters) before running outside of tests. "
                "Set SECRET_KEY_ALLOW_WEAK=1 to allow a random per-process key "
                "(not recommended: it invalidates sessions on restart)."
            )
    else:
        app.config['SECRET_KEY'] = secret_key
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
    from app.routes.chat import chat_bp
    from app.routes.reports import reports_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(reports_bp)

    # F3: force users whose admin-reset password hasn't been changed yet to set a
    # new one before they can use the app. Registered at app scope so it applies
    # to every route (not just auth's), but skips the change-password page itself
    # and static assets to avoid a redirect loop.
    @app.before_request
    def _enforce_forced_password_reset():
        from flask import request, redirect, url_for
        from flask_login import current_user
        if (current_user.is_authenticated
                and getattr(current_user, 'force_password_reset', False)
                and request.endpoint != 'auth.change_password'
                and not request.path.startswith('/static')):
            return redirect(url_for('auth.change_password'))

    # ------------------------------------------------------------------
    # Timezone policy (see Q4 in findings/Case-Tool-Findings.md).
    #
    # Single consistent rule: datetimes are *stored* as naive UTC and are only
    # ever *converted to a wall-clock label* in exactly one place — this
    # `local_fmt` filter. Everything that displays a date/time in a template
    # must go through it; nothing should call .strftime() on a stored datetime
    # directly (that would print the raw UTC label as if it were local time).
    #
    # Conversion is DST-safe: we attach UTC to a naive value (or trust an
    # already-aware one) and let astimezone() do the wall-clock math, so a
    # switch in daylight-saving does not shift the displayed hour.
    # ------------------------------------------------------------------
    @app.template_filter('local_fmt')
    def to_local_fmt(dt, fmt='%Y-%m-%d %H:%M'):
        if dt is None:
            return ''
        from datetime import timezone
        # Naive datetimes are stored as UTC; aware ones are used as-is.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime(fmt)

    from app.routes.reports import _format_hours
    @app.template_filter('format_hours')
    def to_format_hours(hours):
        return _format_hours(hours)

    # F8: format remaining business hours as "Xh Ym" (or "Overdue"/"N/A") for the
    # SLA/OLA countdown shown in view_case.html.
    @app.template_filter('format_remaining')
    def to_format_remaining(hours):
        if hours is None:
            return 'N/A'
        if hours <= 0:
            return 'Overdue'
        whole = int(hours // 1)
        minutes = int(round((hours - whole) * 60))
        if minutes == 60:  # rounding can push us into the next hour
            whole += 1
            minutes = 0
        return f'{whole}h {minutes:02d}m'

    # F7: expose nav badge counts (unread notifications, unassigned cases) and a
    # short recent list for the inline dropdown. Kept cheap: one count query plus
    # one ordered query, only for authenticated users.
    @app.context_processor
    def _nav_counts():
        from flask_login import current_user
        from app.routes.cases import unassigned_case_count
        if not current_user.is_authenticated:
            return {'unread_notification_count': 0, 'unassigned_case_count': 0,
                    'recent_notifications': []}
        from app.models import Notification
        try:
            unread = Notification.unread_count(current_user.id)
            recent = (Notification.query
                      .filter_by(recipient_id=current_user.id)
                      .order_by(Notification.created_at.desc())
                      .limit(5).all())
        except Exception:
            unread, recent = 0, []
        return {
            'unread_notification_count': unread,
            'unassigned_case_count': unassigned_case_count(current_user) if current_user.is_staff else 0,
            'recent_notifications': recent,
        }

    # Q2: schema (migrations) and seed data are applied on the serve path only.
    # We skip both during `flask db ...` CLI invocations so the command itself
    # owns migration execution and we avoid nested upgrade()/stamp()/seed
    # conflicts against a live database.
    if not _is_flask_db_command():
        _initialize_database(app)
        with app.app_context():
            _seed_initial_data(app)

    if not testing:
        from apscheduler.schedulers.background import BackgroundScheduler
        from app.scheduler import run_ola_sla_update

        def _purge_cases(ctx_app):
            from app.routes.cases import purge_expired_cases
            with ctx_app.app_context():
                purge_expired_cases(actor_name='scheduler')

        scheduler = BackgroundScheduler()
        scheduler.add_job(
            func=run_ola_sla_update,
            trigger='interval',
            minutes=1,
            args=[app],
            id='ola_sla_updater',
            replace_existing=True,
        )
        # F5: daily retention purge (03:00 UTC). Soft-deleted cases older than
        # CASE_RETENTION_DAYS are hard-removed. Disabled when <= 0.
        scheduler.add_job(
            func=_purge_cases,
            trigger='cron',
            hour=3,
            args=[app],
            id='case_retention_purge',
            replace_existing=True,
            misfire_grace_time=3600,
        )
        app.scheduler = scheduler  # exposed for introspection/test teardown
        scheduler.start()

        # Q3: stop the scheduler cleanly on process stop (server reload /
        # supervisor SIGTERM) instead of leaving it running until the OS reaps
        # the process. Signal handlers can only be installed from the main
        # thread, and must not clobber pytest's own signal handling during the
        # test session — hence the guard below.
        import signal
        import sys

        def _handle_process_stop(signum, frame):
            scheduler.shutdown(wait=False)
            raise SystemExit(0)

        if 'pytest' not in sys.modules:
            for _sig in (signal.SIGTERM, signal.SIGINT):
                try:
                    signal.signal(_sig, _handle_process_stop)
                except ValueError:
                    # Not running in the main thread (e.g. a worker thread);
                    # signal wiring is skipped rather than failing startup.
                    pass

    return app
