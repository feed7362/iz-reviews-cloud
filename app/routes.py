# -*- coding: utf-8 -*-
"""Маршрути вебзастосунку: обробка запитів користувачів."""
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, jsonify, abort, session)
from . import db, ai
from .security import (admin_required, rate_limited, check_password,
                       login_blocked, record_failed_login, safe_next)

bp = Blueprint('main', __name__)


# ------------------------------------------------------------------ ІЗ1: CRUD
@bp.route('/')
def index():
    category_id = request.args.get('category', type=int)
    sentiment = request.args.get('sentiment') or None
    reviews = db.list_reviews(category_id=category_id, sentiment=sentiment)
    return render_template('index.html',
                           reviews=reviews,
                           categories=db.list_categories(),
                           sel_category=category_id,
                           sel_sentiment=sentiment or '')


@bp.route('/review/new', methods=['GET', 'POST'])
def new_review():
    categories = db.list_categories()
    if request.method == 'POST':
        f = request.form
        errors = []
        name = (f.get('name') or '').strip()
        email = (f.get('email') or '').strip()
        product = (f.get('product') or '').strip()
        body = (f.get('body') or '').strip()
        if len(name) < 2:
            errors.append('Вкажіть ім’я (щонайменше 2 символи).')
        if '@' not in email or len(email) < 5:
            errors.append('Вкажіть коректну електронну пошту.')
        if len(product) < 2:
            errors.append('Вкажіть назву товару.')
        if len(body) < 10:
            errors.append('Текст відгуку має містити щонайменше 10 символів.')
        try:
            rating = int(f.get('rating', 0))
        except ValueError:
            rating = 0
        if not 1 <= rating <= 5:
            errors.append('Оцінка має бути від 1 до 5.')
        try:
            category_id = int(f.get('category_id', 0))
        except ValueError:
            category_id = 0
        if category_id not in {c['id'] for c in categories}:
            errors.append('Оберіть категорію зі списку.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('new_review.html', categories=categories, form=f), 400

        user = db.upsert_user(name, email)
        review = db.add_review(user['id'], category_id, product, body, rating)

        # ІЗ2: одразу після збереження відгук аналізується модулем ШІ
        if f.get('analyse'):
            res = ai.analyse(body)
            db.save_analysis(review['id'], res['sentiment'], res['confidence'], res['model'])

        flash('Відгук збережено.', 'ok')
        return redirect(url_for('main.review_detail', review_id=review['id']))

    return render_template('new_review.html', categories=categories, form={})


@bp.route('/review/<int:review_id>')
def review_detail(review_id):
    review = db.get_review(review_id)
    if not review:
        abort(404)
    return render_template('review.html', r=review)


@bp.route('/review/<int:review_id>/delete', methods=['POST'])
@admin_required
def remove_review(review_id):
    if not db.get_review(review_id):
        abort(404)
    db.delete_review(review_id)
    flash('Відгук видалено.', 'ok')
    return redirect(url_for('main.index'))


# ------------------------------------------------------- ІЗ2: модуль ШІ
@bp.route('/review/<int:review_id>/analyse', methods=['POST'])
@rate_limited
def analyse_review(review_id):
    review = db.get_review(review_id)
    if not review:
        abort(404)
    res = ai.analyse(review['body'])
    db.save_analysis(review_id, res['sentiment'], res['confidence'], res['model'])
    flash('Аналіз виконано: %s (%.2f) - %s'
          % (res['sentiment'], res['confidence'], res['model']), 'ok')
    return redirect(url_for('main.review_detail', review_id=review_id))


@bp.route('/analyse-all', methods=['POST'])
@admin_required
def analyse_all():
    pending = db.unanalysed_reviews()
    for row in pending:
        res = ai.analyse(row['body'])
        db.save_analysis(row['id'], res['sentiment'], res['confidence'], res['model'])
    flash('Проаналізовано відгуків: %d' % len(pending), 'ok')
    return redirect(url_for('main.dashboard'))


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Ліміт рахує лише невдалі спроби - захист від перебору пароля.
        if login_blocked():
            flash('Забагато невдалих спроб входу. Спробуйте пізніше.', 'error')
            return render_template('login.html'), 429
        if check_password(request.form.get('password', '')):
            session['is_admin'] = True
            flash('Вхід виконано.', 'ok')
            return redirect(safe_next(request.args.get('next')) or url_for('main.index'))
        record_failed_login()
        flash('Невірний пароль.', 'error')
    return render_template('login.html')


@bp.route('/logout', methods=['POST'])
def logout():
    session.pop('is_admin', None)
    flash('Вихід виконано.', 'ok')
    return redirect(url_for('main.index'))


@bp.route('/dashboard')
def dashboard():
    return render_template('dashboard.html', s=db.stats(), ai_status=ai.service_status())


# ------------------------------------------------------------------- API
@bp.route('/api/analyse', methods=['POST'])
@rate_limited
def api_analyse():
    """Аналіз довільного тексту без збереження - для перевірки модуля ШІ."""
    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    if len(text) < 3:
        return jsonify({'error': 'Поле text має містити щонайменше 3 символи'}), 400
    return jsonify(ai.analyse(text))


@bp.route('/api/stats')
def api_stats():
    return jsonify(db.stats())


@bp.route('/health')
def health():
    try:
        db.query('SELECT 1')
        database = 'ok'
    except Exception as exc:
        database = 'error: %s' % type(exc).__name__
    return jsonify({'status': 'ok', 'database': database, 'ai': ai.service_status()})
