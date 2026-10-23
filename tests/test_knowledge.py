"""F11: knowledge base, resolved-case retrieval, and chat RAG grounding."""
from datetime import datetime

from app import db as sql_db
from app.models import AuditLog, Case, Comment, Group, KnowledgeArticle, User


def _make_article(app, *, title='Password reset', body='Use the reset link.',
                  published=True, category='Account', tags='password, login',
                  source_case_id=None):
    with app.app_context():
        article = KnowledgeArticle(
            title=title, body=body, is_published=published,
            category=category, tags=tags, source_case_id=source_case_id,
        )
        sql_db.session.add(article)
        sql_db.session.commit()
        return article.id


def _make_case(app, *, title, description='details', status='resolved',
               group_id=None, deleted=False, comments=None):
    with app.app_context():
        user = User.query.filter_by(username='staffadmin').first()
        if user is None:
            user = User.query.first()
        if user is None:
            user = User(username='fixtureuser', email='fixture@example.com',
                        is_staff=True)
            user.set_password('Str0ng!Passw0rd')
            sql_db.session.add(user)
            sql_db.session.commit()
        case = Case(
            title=title, description=description, user_id=user.id,
            assignment_group_id=group_id, status=status,
            case_type='Technical', category='Software',
            deleted_at=datetime.utcnow() if deleted else None,
        )
        sql_db.session.add(case)
        sql_db.session.commit()
        for content in (comments or []):
            sql_db.session.add(Comment(content=content, user_id=user.id,
                                       case_id=case.id))
        sql_db.session.commit()
        return case.id


def _triage_group_id(app):
    with app.app_context():
        group = Group.query.filter_by(name='Triage').first()
        if group is None:
            group = Group(name='Triage')
            sql_db.session.add(group)
            sql_db.session.commit()
        return group.id


# ---------------------------------------------------------------------------
# Browsing and access control
# ---------------------------------------------------------------------------


def test_knowledge_requires_login(app):
    r = app.test_client().get('/knowledge/')
    assert r.status_code == 302


def test_published_article_visible_to_end_user(plain_client, app):
    aid = _make_article(app, title='Reset your password safely',
                        body='Open the account page and choose reset.')
    r = plain_client.get('/knowledge/')
    assert r.status_code == 200
    assert 'Reset your password safely' in r.get_data(as_text=True)

    r = plain_client.get(f'/knowledge/{aid}')
    assert r.status_code == 200
    assert 'Open the account page' in r.get_data(as_text=True)


def test_draft_hidden_from_end_user(plain_client, app):
    aid = _make_article(app, title='Internal draft', published=False)
    assert plain_client.get(f'/knowledge/{aid}').status_code == 404


def test_draft_previewable_by_staff(staff_client, app):
    aid = _make_article(app, title='Internal draft', published=False)
    assert staff_client.get(f'/knowledge/{aid}').status_code == 200


def test_non_admin_cannot_manage_knowledge(plain_client, app):
    r = plain_client.get('/knowledge/admin')
    assert r.status_code == 302
    r = plain_client.post('/knowledge/admin/new', data={
        'title': 'Nope', 'body': 'Nope', 'is_published': 'y',
    })
    assert r.status_code == 302
    with app.app_context():
        assert KnowledgeArticle.query.filter_by(title='Nope').count() == 0


# ---------------------------------------------------------------------------
# Admin CRUD + case promotion
# ---------------------------------------------------------------------------


def test_admin_create_article_and_audit(staff_client, app):
    r = staff_client.post('/knowledge/admin/new', data={
        'title': 'VPN setup', 'body': 'Install the client and sign in.',
        'category': 'Network', 'tags': 'vpn, remote', 'is_published': 'y',
        'source_case_id': '',
    }, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        article = KnowledgeArticle.query.filter_by(title='VPN setup').one()
        assert article.is_published is True
        assert article.category == 'Network'
        assert AuditLog.query.filter_by(
            action='knowledge_create', target_id=article.id).count() == 1


def test_create_article_prefills_from_case_and_links_source(staff_client, app):
    gid = _triage_group_id(app)
    cid = _make_case(app, title='Printer offline', description='Printer queue stuck',
                     group_id=gid, comments=['Cleared the spooler and re-added it.'])

    r = staff_client.get(f'/knowledge/admin/new?case_id={cid}')
    body = r.get_data(as_text=True)
    assert 'Printer offline' in body
    assert 'Printer queue stuck' in body
    assert 'Cleared the spooler' in body

    r = staff_client.post('/knowledge/admin/new', data={
        'title': 'Fix a stuck printer queue',
        'body': 'Clear the spooler and re-add the printer.',
        'category': 'Hardware', 'tags': 'printer', 'is_published': 'y',
        'source_case_id': str(cid),
    }, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        article = KnowledgeArticle.query.filter_by(
            title='Fix a stuck printer queue').one()
        assert article.source_case_id == cid


def test_edit_toggle_and_delete_article(staff_client, app):
    aid = _make_article(app, title='Original title', published=True)

    r = staff_client.post(f'/knowledge/admin/{aid}/edit', data={
        'title': 'Updated title', 'body': 'Updated body',
        'category': 'Other', 'tags': 'updated', 'is_published': 'y',
        'source_case_id': '',
    }, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        article = KnowledgeArticle.query.get(aid)
        assert article.title == 'Updated title'

    staff_client.post(f'/knowledge/admin/{aid}/toggle', follow_redirects=True)
    with app.app_context():
        assert KnowledgeArticle.query.get(aid).is_published is False

    staff_client.post(f'/knowledge/admin/{aid}/delete', follow_redirects=True)
    with app.app_context():
        assert KnowledgeArticle.query.get(aid) is None


# ---------------------------------------------------------------------------
# Retrieval quality and scoping
# ---------------------------------------------------------------------------


def test_search_returns_relevant_published_article(plain_client, app):
    _make_article(app, title='Reset your password',
                  body='Use the account page to reset a forgotten password.')
    _make_article(app, title='Printer setup guide', tags='printer, hardware',
                  body='Install the network printer driver.')

    r = plain_client.get('/knowledge/?q=forgotten+password+reset')
    body = r.get_data(as_text=True)
    assert 'Reset your password' in body
    assert 'Printer setup guide' not in body


def test_draft_not_returned_in_search(plain_client, app):
    _make_article(app, title='Secret draft about zebras', published=False)
    r = plain_client.get('/knowledge/?q=zebras')
    assert 'Secret draft about zebras' not in r.get_data(as_text=True)


def test_staff_search_includes_resolved_cases_in_their_groups(staff_client, app):
    gid = _triage_group_id(app)
    visible = _make_case(
        app, title='Flux capacitor overload', group_id=gid,
        comments=['Replaced the capacitor and verified output.'])
    _make_case(app, title='Flux capacitor in another group', group_id=None)

    r = staff_client.get('/knowledge/?q=capacitor')
    body = r.get_data(as_text=True)
    assert 'Matching resolved cases' in body
    assert f'Case #{visible}' in body


def test_non_admin_staff_search_only_sees_own_group_cases(app):
    gid = _triage_group_id(app)
    with app.app_context():
        other = Group(name='Other Team')
        sql_db.session.add(other)
        sql_db.session.commit()
        other_id = other.id
        user = User(username='helper', email='helper@example.com', is_staff=True)
        user.set_password('Str0ng!Passw0rd')
        user.groups.append(Group.query.get(gid))
        sql_db.session.add(user)
        sql_db.session.commit()

    own = _make_case(app, title='Nebula own-team fix', group_id=gid)
    foreign = _make_case(app, title='Nebula foreign-team fix', group_id=other_id)

    client = app.test_client()
    client.post('/login', data={'username': 'helper',
                                'password': 'Str0ng!Passw0rd'},
                follow_redirects=True)
    body = client.get('/knowledge/?q=nebula').get_data(as_text=True)
    assert f'Case #{own}' in body
    assert f'Case #{foreign}' not in body


def test_resolved_case_search_ignores_open_and_deleted_cases(staff_client, app):
    gid = _triage_group_id(app)
    _make_case(app, title='Unobtainium open issue', group_id=gid, status='open')
    _make_case(app, title='Unobtainium deleted issue', group_id=gid, deleted=True)

    r = staff_client.get('/knowledge/?q=unobtainium')
    assert 'Matching resolved cases' not in r.get_data(as_text=True)


def test_search_rank_prefers_title_match(app):
    from app import knowledge
    with app.app_context():
        sql_db.session.add(KnowledgeArticle(
            title='Password reset', body='Unrelated words here.',
            is_published=True))
        sql_db.session.add(KnowledgeArticle(
            title='Generic account help',
            body='You can reset your password from the account page.',
            is_published=True))
        sql_db.session.commit()
        results = knowledge.search('password reset', include_cases=False)
    assert results[0]['title'] == 'Password reset'


# ---------------------------------------------------------------------------
# Chat grounding
# ---------------------------------------------------------------------------


class _FakeResponse:
    def iter_lines(self, decode_unicode=False):
        return iter([
            'data: {"choices":[{"delta":{"content":"grounded"}}]}',
            'data: [DONE]',
        ])


def _capture_llm(monkeypatch):
    captured = {}

    def fake_post(url, json=None, stream=False, timeout=None):
        captured['url'] = url
        captured['json'] = json
        return _FakeResponse()

    monkeypatch.setattr('app.routes.chat.requests.post', fake_post)
    return captured


def test_chat_user_injects_published_article(monkeypatch, plain_client, app):
    _make_article(app, title='Password reset steps',
                  body='Open Account, choose Reset Password, and follow the email link.')
    captured = _capture_llm(monkeypatch)

    r = plain_client.post('/chat/user', json={'messages': [
        {'role': 'user', 'content': 'How do I reset my password?'},
    ]})
    assert r.status_code == 200
    assert b'grounded' in r.get_data()

    system = captured['json']['messages'][0]
    assert system['role'] == 'system'
    assert 'Password reset steps' in system['content']
    assert 'follow the email link' in system['content']


def test_chat_user_does_not_see_drafts_or_resolved_cases(monkeypatch, plain_client, app):
    _make_article(app, title='Draft quasar reset', published=False)
    _make_case(app, title='Quasar ticket', description='quasar secret notes',
               group_id=None)
    captured = _capture_llm(monkeypatch)

    plain_client.post('/chat/user', json={'messages': [
        {'role': 'user', 'content': 'quasar'},
    ]})
    system = captured['json']['messages'][0]['content']
    assert 'Draft quasar reset' not in system
    assert 'quasar secret notes' not in system


def test_chat_staff_injects_resolved_case(monkeypatch, staff_client, app):
    gid = _triage_group_id(app)
    _make_case(app, title='Quasar outage playbook',
               description='Restart the quasar service and clear its cache.',
               group_id=gid)
    captured = _capture_llm(monkeypatch)

    r = staff_client.post('/chat/staff', json={'messages': [
        {'role': 'user', 'content': 'How do I fix a quasar outage?'},
    ]})
    assert r.status_code == 200
    system = captured['json']['messages'][0]['content']
    assert 'Quasar outage playbook' in system
    assert 'clear its cache' in system


def test_chat_without_relevant_context_leaves_prompt_unchanged(monkeypatch, plain_client):
    captured = _capture_llm(monkeypatch)
    plain_client.post('/chat/user', json={'messages': [
        {'role': 'user', 'content': 'zzzz-no-such-term-zzzz'},
    ]})
    system = captured['json']['messages'][0]['content']
    assert 'reference material' not in system
    assert 'helpful support assistant' in system


def test_chat_ignores_malformed_message_entries(monkeypatch, plain_client):
    captured = _capture_llm(monkeypatch)
    r = plain_client.post('/chat/user', json={'messages': [
        None, {'role': 'user', 'content': 123},
    ]})
    assert r.status_code == 200
    assert captured['json']['messages'][0]['role'] == 'system'


def test_draft_from_case_includes_description_and_comments(app):
    from app import knowledge
    gid = _triage_group_id(app)
    cid = _make_case(app, title='Mail sync failure', group_id=gid,
                     description='Mailbox not syncing.',
                     comments=['Recreated the profile.', 'Confirmed sync works.'])
    with app.app_context():
        case = Case.query.get(cid)
        draft = knowledge.draft_from_case(case)
    assert draft['title'] == 'Mail sync failure'
    assert 'Mailbox not syncing.' in draft['body']
    assert 'Recreated the profile.' in draft['body']
    assert draft['source_case_id'] == cid
