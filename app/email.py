import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from app import db
from app.models import OrgSetting, EmailLog
from app import crypto


def _get_smtp_config():
    org = OrgSetting.get()
    return {
        'server': org.smtp_server or 'localhost',
        'port': org.smtp_port or 587,
        'username': org.smtp_username or '',
        # S6: decrypt at rest; falls back to plaintext for legacy/unset keys.
        'password': crypto.decrypt_or_plain(org.smtp_password or ''),
        'from_email': org.smtp_from_email or 'noreply@example.com',
        'use_tls': org.smtp_use_tls if org.smtp_use_tls is not None else True,
    }


def send_email(to, subject, body, case_id=None):
    config = _get_smtp_config()
    if not config['server'] or config['server'] == 'localhost':
        log = EmailLog(recipient=to, subject=subject, body=body, case_id=case_id)
        db.session.add(log)
        db.session.commit()
        return True

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = config['from_email']
    msg['To'] = to

    try:
        with smtplib.SMTP(config['server'], config['port']) as s:
            if config['use_tls']:
                s.starttls()
            if config['username'] and config['password']:
                s.login(config['username'], config['password'])
            s.send_message(msg)
    except Exception:
        log = EmailLog(
            recipient=to, subject=subject, body=body,
            case_id=case_id, direction='outgoing'
        )
        db.session.add(log)
        db.session.commit()
        return False

    log = EmailLog(
        recipient=to, subject=subject, body=body,
        case_id=case_id, direction='outgoing'
    )
    db.session.add(log)
    db.session.commit()
    return True


def _case_summary(case):
    return (
        f'Case #{case.id}: {case.title}\n'
        f'Type: {case.case_type or "N/A"}\n'
        f'Category: {case.category or "N/A"}\n'
        f'Status: {case.status}\n'
        f'Description: {case.description[:200]}'
    )


def _notify_user(user, subject, body, case_id=None):
    """Send a notification email.

    Returns True when no email needed sending or it was sent successfully, and
    False when an attempted send failed (Q6: so callers can surface the error).
    """
    if user and user.email:
        return send_email(user.email, subject, body, case_id=case_id)
    return True


def notify_group_assignment(case):
    if not case.assignment_group or not case.assignment_group.manager:
        return True
    mgr = case.assignment_group.manager
    subject = f'[Case #{case.id}] New case assigned to {case.assignment_group.name}'
    body = (
        f'A new case has been assigned to your group "{case.assignment_group.name}".\n\n'
        f'{_case_summary(case)}'
    )
    return _notify_user(mgr, subject, body, case_id=case.id)


def notify_user_assignment(case, user):
    subject = f'[Case #{case.id}] Case assigned to you'
    body = (
        f'Case #{case.id} has been assigned to you.\n\n'
        f'{_case_summary(case)}'
    )
    return _notify_user(user, subject, body, case_id=case.id)


def notify_comment_added(comment, case, commenter):
    if case.assigned_to and commenter.id != case.assigned_to.id:
        recipient = case.assigned_to
    elif case.assignment_group and case.assignment_group.manager:
        recipient = case.assignment_group.manager
    else:
        recipient = None

    if not recipient or recipient.id == commenter.id:
        return True

    subject = f'[Case #{case.id}] New comment by {commenter.username}'
    body = (
        f'{commenter.username} added a comment to Case #{case.id}:\n\n'
        f'"{comment.content}"'
    )
    return _notify_user(recipient, subject, body, case_id=case.id)


def notify_resolution(case, reason, last_comment=None):
    if not case.user or not case.user.email:
        return True
    subject = f'[Case #{case.id}] Case resolved'
    body = (
        f'Case #{case.id} has been resolved.\n\n'
        f'{_case_summary(case)}\n'
    )
    if last_comment:
        body += f'\nLast comment:\n"{last_comment.content}"\n'
    body += f'\nResolution note: {reason}'
    return _notify_user(case.user, subject, body, case_id=case.id)


def notify_escalation(case, event_type, details):
    if case.assigned_to:
        recipient = case.assigned_to
    elif case.assignment_group and case.assignment_group.manager:
        recipient = case.assignment_group.manager
    else:
        recipient = None

    if not recipient:
        return True

    label = event_type.replace('_', ' ').title()
    subject = f'[Case #{case.id}] {label}'
    body = (
        f'Case #{case.id} has triggered an escalation: {label}\n\n'
        f'{_case_summary(case)}\n\n'
        f'Details: {details or "N/A"}'
    )
    return _notify_user(recipient, subject, body, case_id=case.id)
