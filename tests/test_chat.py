"""Tests for the chat proxy input validation (B6)."""


def test_chat_malformed_json_returns_400(plain_client):
    r = plain_client.post('/chat/user', data='not json',
                          content_type='application/json')
    assert r.status_code == 400


def test_chat_messages_not_a_list_returns_400(plain_client):
    r = plain_client.post('/chat/user', json={'messages': 'nope'})
    assert r.status_code == 400


def test_chat_empty_body_returns_400(plain_client):
    r = plain_client.post('/chat/user', data='',
                          content_type='application/json')
    assert r.status_code == 400


def test_chat_staff_endpoint_blocks_non_staff(plain_client):
    # non-staff hitting the staff endpoint -> 403 (before any JSON handling)
    r = plain_client.post('/chat/staff', json={'messages': []})
    assert r.status_code == 403


def test_chat_staff_endpoint_requires_non_staff(app, staff_client):
    # staff user hitting the user endpoint -> 403
    r = staff_client.post('/chat/user', json={'messages': []})
    assert r.status_code == 403
