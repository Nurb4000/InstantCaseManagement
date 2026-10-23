"""F11: knowledge-base browsing, admin management, and case promotion."""
from datetime import datetime
from functools import wraps

from flask import (
    Blueprint, abort, flash, redirect, render_template, request, url_for,
)
from flask_login import current_user, login_required

from app import db, knowledge
from app.audit import log_audit
from app.forms import KnowledgeArticleForm
from app.models import Case, KnowledgeArticle

knowledge_bp = Blueprint('knowledge', __name__, url_prefix='/knowledge')


def knowledge_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Access denied')
            return redirect(url_for('cases.dashboard'))
        return f(*args, **kwargs)
    return decorated


def _source_case(case_id):
    """Load a live (non-soft-deleted) case, or None for an absent/invalid id."""
    try:
        case_id = int(case_id)
    except (TypeError, ValueError):
        return None
    case = Case.query.get(case_id)
    if case is None or case.deleted_at is not None:
        return None
    return case


@knowledge_bp.route('/')
@login_required
def list_articles():
    q = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()

    if q:
        results = knowledge.search(
            q, user=current_user, include_cases=current_user.is_staff, limit=50
        )
        articles = []
        for result in results:
            if result['kind'] != 'article':
                continue
            article = KnowledgeArticle.query.get(result['id'])
            if article is not None:
                articles.append(article)
        case_results = [r for r in results if r['kind'] == 'case']
    else:
        query = KnowledgeArticle.query.filter_by(is_published=True)
        if category:
            query = query.filter(KnowledgeArticle.category == category)
        articles = query.order_by(KnowledgeArticle.updated_at.desc()).all()
        case_results = []

    categories = [
        row[0] for row in db.session.query(KnowledgeArticle.category)
        .filter(KnowledgeArticle.is_published.is_(True),
                KnowledgeArticle.category.isnot(None),
                KnowledgeArticle.category != '')
        .distinct().order_by(KnowledgeArticle.category.asc()).all()
    ]

    return render_template(
        'knowledge/list.html', articles=articles, case_results=case_results,
        categories=categories, q=q, category=category,
    )


@knowledge_bp.route('/<int:article_id>')
@login_required
def view_article(article_id):
    article = KnowledgeArticle.query.get_or_404(article_id)
    if not article.is_published and not current_user.is_staff:
        abort(404)
    source_case = None
    if article.source_case_id:
        source_case = _source_case(article.source_case_id)
    return render_template('knowledge/view.html', article=article,
                           source_case=source_case)


@knowledge_bp.route('/admin')
@login_required
@knowledge_admin_required
def manage():
    articles = (KnowledgeArticle.query
                .order_by(KnowledgeArticle.updated_at.desc()).all())
    return render_template('knowledge/manage.html', articles=articles)


@knowledge_bp.route('/admin/new', methods=['GET', 'POST'])
@login_required
@knowledge_admin_required
def create_article():
    form = KnowledgeArticleForm()
    if not form.is_submitted():
        source = _source_case(request.args.get('case_id'))
        if source is not None:
            draft = knowledge.draft_from_case(source)
            form.title.data = draft['title']
            form.body.data = draft['body']
            form.category.data = draft['category']
            form.tags.data = draft['tags']
            form.source_case_id.data = draft['source_case_id']
        else:
            form.is_published.data = True

    if form.validate_on_submit():
        source = _source_case(form.source_case_id.data)
        article = KnowledgeArticle(
            title=form.title.data,
            body=form.body.data,
            category=form.category.data or None,
            tags=form.tags.data or None,
            is_published=form.is_published.data,
            created_by_id=current_user.id,
            source_case_id=source.id if source else None,
        )
        db.session.add(article)
        db.session.commit()
        log_audit('knowledge_create', target_type='KnowledgeArticle',
                  target_id=article.id, details=f'title="{article.title}"')
        flash(f'Knowledge article "{article.title}" created')
        return redirect(url_for('knowledge.manage'))

    return render_template('knowledge/form.html', form=form,
                           title='New Knowledge Article', article=None)


@knowledge_bp.route('/admin/<int:article_id>/edit', methods=['GET', 'POST'])
@login_required
@knowledge_admin_required
def edit_article(article_id):
    article = KnowledgeArticle.query.get_or_404(article_id)
    form = KnowledgeArticleForm(obj=article)
    if form.validate_on_submit():
        source = _source_case(form.source_case_id.data)
        article.title = form.title.data
        article.body = form.body.data
        article.category = form.category.data or None
        article.tags = form.tags.data or None
        article.is_published = form.is_published.data
        article.source_case_id = source.id if source else None
        article.updated_at = datetime.utcnow()
        db.session.commit()
        log_audit('knowledge_edit', target_type='KnowledgeArticle',
                  target_id=article.id, details=f'title="{article.title}"')
        flash('Knowledge article updated')
        return redirect(url_for('knowledge.manage'))

    return render_template('knowledge/form.html', form=form,
                           title='Edit Knowledge Article', article=article)


@knowledge_bp.route('/admin/<int:article_id>/toggle', methods=['POST'])
@login_required
@knowledge_admin_required
def toggle_article(article_id):
    article = KnowledgeArticle.query.get_or_404(article_id)
    article.is_published = not article.is_published
    article.updated_at = datetime.utcnow()
    db.session.commit()
    status = 'published' if article.is_published else 'unpublished'
    log_audit('knowledge_toggle', target_type='KnowledgeArticle',
              target_id=article.id,
              details=f'title="{article.title}" published={article.is_published}')
    flash(f'Article "{article.title}" is now {status}')
    return redirect(url_for('knowledge.manage'))


@knowledge_bp.route('/admin/<int:article_id>/delete', methods=['POST'])
@login_required
@knowledge_admin_required
def delete_article(article_id):
    article = KnowledgeArticle.query.get_or_404(article_id)
    log_audit('knowledge_delete', target_type='KnowledgeArticle',
              target_id=article.id, details=f'title="{article.title}"')
    db.session.delete(article)
    db.session.commit()
    flash('Knowledge article deleted')
    return redirect(url_for('knowledge.manage'))
