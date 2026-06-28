import os
from flask import Blueprint, render_template, request, Response, stream_with_context
from flask_login import login_required, current_user
import requests

from app import limiter, csrf

chat_bp = Blueprint('chat', __name__)

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
    return _proxy_chat(LLAMA_CPP_USER_URL, CHAT_USER_SYSTEM_PROMPT)


@chat_bp.route('/chat/staff', methods=['POST'])
@csrf.exempt
@login_required
@limiter.limit('30 per minute')
def chat_staff():
    if not current_user.is_staff:
        return {'error': 'Only staff can use the staff chat endpoint'}, 403
    return _proxy_chat(LLAMA_CPP_STAFF_URL, CHAT_STAFF_SYSTEM_PROMPT)


def _proxy_chat(llama_url, system_prompt):
    data = request.get_json(force=True)
    messages = data.get('messages', [])

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
