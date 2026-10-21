import os

from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy.exc import IntegrityError

from app import db, limiter, login_manager, auth_security
from app.models import User
from app.forms import LoginForm, RegisterForm, ChangePasswordForm, LoginMfaForm, TwoFactorEnableForm, TwoFactorDisableForm

auth_bp = Blueprint('auth', __name__)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('cases.dashboard'))
    # S4: slow down brute force before we even validate credentials.
    ip = request.remote_addr or 'unknown'
    if auth_security.ip_in_hard_cap(ip):
        auth_security.record_login_attempt(None, ip, success=False)
        flash('Too many failed attempts. Please try again later.', 'warning')
        return render_template('login.html', form=LoginForm(), captcha_challenge=None)
    auth_security.apply_login_delay(ip)

    # S4 follow-up: once an IP accrues enough failures, require a CAPTCHA.
    challenge = None
    if auth_security.captcha_required_for_ip(ip):
        challenge = auth_security.ensure_captcha_challenge()

    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data
        if challenge is not None:
            provided = request.form.get('captcha', '').strip()
            if not auth_security.captcha_matches(provided):
                auth_security.record_login_attempt(username, ip, success=False)
                flash('Security check failed. Please try again.', 'error')
                challenge = auth_security.regenerate_captcha_challenge()
                return render_template('login.html', form=form, captcha_challenge=challenge)
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(form.password.data):
            auth_security.record_login_attempt(username, ip, success=True)
            auth_security.clear_captcha_for_session()
            # F10: users with TOTP enabled must supply a second factor before the
            # session is established. We stash the verified user id (not a token)
            # and bounce to the code entry step rather than logging in yet.
            if user.totp_secret:
                session['mfa_user_id'] = user.id
                session.modified = True
                return redirect(url_for('auth.login_mfa'))
            login_user(user)
            return redirect(url_for('cases.dashboard'))
        auth_security.record_login_attempt(username, ip, success=False)
        flash('Invalid username or password')
    return render_template('login.html', form=form, captcha_challenge=challenge)


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    # S8: self-registration is opt-out. Admins can close registration (e.g. for
    # admin-approved onboarding) by setting ALLOW_SELF_REGISTRATION=false.
    allow_register = os.environ.get('ALLOW_SELF_REGISTRATION', 'true').lower() not in (
        '0', 'false', 'no', 'off'
    )
    if not allow_register:
        flash('Self-registration is currently disabled. Contact your administrator.')
        return redirect(url_for('auth.login'))
    if current_user.is_authenticated:
        return redirect(url_for('cases.dashboard'))
    form = RegisterForm()
    if form.validate_on_submit():
        existing = User.query.filter(
            (User.username == form.username.data) | (User.email == form.email.data)
        ).first()
        if existing:
            flash('Username or email already exists')
            return render_template('register.html', form=form)
        user = User(
            username=form.username.data,
            email=form.email.data,
        )
        user.set_password(form.password.data)
        try:
            db.session.add(user)
            db.session.commit()
            flash('Registration successful. Please login.')
            return redirect(url_for('auth.login'))
        except IntegrityError:
            db.session.rollback()
            flash('Username or email already exists')
    return render_template('register.html', form=form)


@auth_bp.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash('Current password is incorrect')
            return render_template('change_password.html', form=form)
        current_user.set_password(form.new_password.data)
        # F3: clearing an admin-forced reset lets the user proceed normally.
        current_user.force_password_reset = False
        db.session.commit()
        flash('Password changed successfully')
        return redirect(url_for('cases.dashboard'))
    return render_template('change_password.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))


@auth_bp.route('/login/two-factor', methods=['GET', 'POST'])
def login_mfa():
    """F10: second-factor entry step. The password was already validated; we only
    establish the session once a correct TOTP code is supplied."""
    if current_user.is_authenticated:
        return redirect(url_for('cases.dashboard'))
    user_id = session.get('mfa_user_id')
    if not user_id:
        # No pending verification (e.g. direct navigation) -> start over.
        return redirect(url_for('auth.login'))

    form = LoginMfaForm()
    if form.validate_on_submit():
        user = User.query.get(user_id)
        from app.totp import verify_totp
        if user and user.totp_secret and verify_totp(user.totp_secret, form.code.data):
            session.pop('mfa_user_id', None)
            login_user(user)
            return redirect(url_for('cases.dashboard'))
        flash('Invalid verification code', 'error')
    return render_template('login_two_factor.html', form=form)


@auth_bp.route('/settings/two-factor', methods=['GET', 'POST'])
@login_required
def two_factor_settings():
    """F10: self-service enable/disable of TOTP two-factor authentication."""
    if current_user.totp_secret:
        form = TwoFactorDisableForm()
        if form.validate_on_submit():
            if not current_user.check_password(form.current_password.data):
                form.current_password.errors = ['Current password is incorrect']
                return render_template('two_factor.html', enabled=True, form=form)
            current_user.totp_secret = None
            db.session.commit()
            session.pop('mfa_pending_secret', None)
            flash('Two-factor authentication disabled')
            return redirect(url_for('auth.two_factor_settings'))
        return render_template('two_factor.html', enabled=True, form=form)

    # Disabled: mint a pending secret (shown to the user) unless one exists.
    if not session.get('mfa_pending_secret'):
        from app.totp import generate_secret
        session['mfa_pending_secret'] = generate_secret()
        session.modified = True
    form = TwoFactorEnableForm()
    if form.validate_on_submit():
        from app.totp import verify_totp
        secret = session.get('mfa_pending_secret')
        if secret and verify_totp(secret, form.code.data):
            current_user.totp_secret = secret
            db.session.commit()
            session.pop('mfa_pending_secret', None)
            flash('Two-factor authentication enabled')
            return redirect(url_for('auth.two_factor_settings'))
        form.code.errors = ['Invalid code. Re-enter the code from your authenticator app.']
    from app.totp import provisioning_uri
    return render_template(
        'two_factor.html',
        enabled=False,
        form=form,
        secret=session.get('mfa_pending_secret'),
        uri=provisioning_uri(session['mfa_pending_secret'], current_user.email),
    )
