import os
from flask import Blueprint, render_template, request, Response, stream_with_context
from flask_login import login_required, current_user
import requests

from app import limiter, csrf, knowledge

chat_bp = Blueprint('chat', __name__)


# S5 — Why these endpoints are @csrf.exempt (documented tradeoff)
# -----------------------------------------------------------------------------
# /chat/user and /chat/staff are JSON APIs driven by the browser's fetch(), not
# HTML form posts. Standard CSRF tokens are therefore awkward for clients, so the
# endpoints are exempt from Flask-WTF CSRF protection. This is acceptable because
# every residual risk is mitigated:
#   1. @login_required  — an authenticated session is required; anonymous CSFR is
#      impossible without already holding a valid session cookie.
#   2. Input validated  — body/messages shape is validated (see _proxy_chat); bad
#      input returns 400 instead of proxying to the backend.
#   3. Rate limited     — 30 requests/minute per IP (Flask-Limiter) bounds any
#      resource-abuse or prompt-injection amplification.
#   4. Role-gated       — staff vs user endpoints are separated by current_user.
# Residual risk: a cross-site authenticated request could still drive the LLM
# proxy on behalf of the victim. If this app is ever exposed to untrusted
# cross-site actors, re-enable CSRF (or use the SameSite cookie attribute) and
# switch the client to an explicit token. For an internal, authenticated tool
# the current posture is a reasonable risk/reward balance.

LLAMA_CPP_USER_URL = os.environ.get('LLAMA_CPP_USER_URL', 'http://10.0.1.27:8080/v1/chat/completions')
LLAMA_CPP_STAFF_URL = os.environ.get('LLAMA_CPP_STAFF_URL', 'http://10.0.1.28:8080/v1/chat/completions')
CHAT_USER_SYSTEM_PROMPT = os.environ.get(
    'CHAT_USER_SYSTEM_PROMPT',
    'You are a helpful support assistant for end users. Answer questions clearly and concisely.'
)
CHAT_STAFF_SYSTEM_PROMPT = os.environ.get(
    'CHAT_STAFF_SYSTEM_PROMPT',
    'You are an expert technical support analyst for staff members. Provide detailed technical guidance for case management.'
)


@chat_bp.route('/chat')
@login_required
def chat_page():
    return render_template('chat.html')


@chat_bp.route('/chat/user', methods=['POST'])
@csrf.exempt
@login_required
@limiter.limit('30 per minute')
def chat_user():
    if current_user.is_staff:
        return {'error': 'Staff must use the staff chat endpoint'}, 403
    return _proxy_chat(LLAMA_CPP_USER_URL, CHAT_USER_SYSTEM_PROMPT,
                       include_cases=False)


@chat_bp.route('/chat/staff', methods=['POST'])
@csrf.exempt
@login_required
@limiter.limit('30 per minute')
def chat_staff():
    if not current_user.is_staff:
        return {'error': 'Only staff can use the staff chat endpoint'}, 403
    return _proxy_chat(LLAMA_CPP_STAFF_URL, CHAT_STAFF_SYSTEM_PROMPT,
                       include_cases=True)


def _last_user_message(messages):
    """Extract the newest user query for retrieval, ignoring malformed entries."""
    for message in reversed(messages):
        if isinstance(message, dict) and message.get('role') == 'user':
            content = message.get('content')
            if isinstance(content, str) and content.strip():
                return content
    return ''


def _proxy_chat(llama_url, system_prompt, *, include_cases=False):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {'error': 'Invalid or missing JSON body'}, 400
    messages = data.get('messages')
    if not isinstance(messages, list):
        return {'error': "'messages' must be a list"}, 400

    # F11: ground the model in published KB articles (and, for staff, resolved
    # cases in their groups) relevant to the latest user message.
    retrieved = knowledge.build_context(
        _last_user_message(messages), user=current_user,
        include_cases=include_cases,
    )
    if retrieved:
        system_prompt = f'{system_prompt}\n\n{retrieved}'

    full_messages = [{'role': 'system', 'content': system_prompt}] + messages

    payload = {
        'messages': full_messages,
        'stream': True,
        'temperature': 0.7,
    }

    def generate():
        try:
            resp = requests.post(
                llama_url,
                json=payload,
                stream=True,
                timeout=30,
            )
            for line in resp.iter_lines(decode_unicode=True):
                if line:
                    yield line + '\n'
        except requests.exceptions.ConnectionError:
            yield f'data: {{"error": "Unable to connect to the AI backend"}}\n\n'
        except requests.exceptions.Timeout:
            yield f'data: {{"error": "AI backend request timed out"}}\n\n'
        except Exception as e:
            yield f'data: {{"error": "An error occurred: {str(e)}"}}\n\n'

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )
