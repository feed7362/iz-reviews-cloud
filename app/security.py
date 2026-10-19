# -*- coding: utf-8 -*-
"""Захист застосунку: доступ адміністратора, CSRF та обмеження частоти запитів.

Застосунок розгортається у публічній хмарі, тому дії, які змінюють дані або
витрачають квоту платного сервісу ШІ, не можуть бути доступні анонімно.
"""
import os
import secrets
import time
from collections import defaultdict
from functools import wraps
from hmac import compare_digest
from urllib.parse import urlparse

from flask import session, request, redirect, url_for, flash, jsonify, abort

# Проста пам'ять лічильників. Достатньо для одного процесу gunicorn;
# для кількох робітників потрібне спільне сховище (наприклад Redis).
_hits = defaultdict(list)

RATE_LIMIT = int(os.environ.get('RATE_LIMIT', '20'))        # запитів
RATE_WINDOW = int(os.environ.get('RATE_WINDOW', '600'))     # за секунд
LOGIN_LIMIT = int(os.environ.get('LOGIN_LIMIT', '10'))      # спроб входу
LOGIN_WINDOW = int(os.environ.get('LOGIN_WINDOW', '600'))


def admin_token():
    return os.environ.get('ADMIN_TOKEN', '')


def is_admin():
    return bool(session.get('is_admin'))


def check_password(value):
    token = admin_token()
    if not token:
        return False
    return compare_digest(str(value), token)


# --------------------------------------------------------------- CSRF
def csrf_token():
    """Токен сесії для захисту форм від міжсайтової підробки запиту."""
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_urlsafe(32)
    return session['csrf_token']


def validate_csrf():
    """Перевіряє токен у кожному POST-запиті з форми.

    JSON-запити до API пропускаються: вони не надсилаються браузером
    автоматично з кукою (CORS забороняє крос-доменний JSON без дозволу),
    а сам API не виконує дій зі зміни даних.
    """
    if request.method != 'POST':
        return
    if request.path.startswith('/api/'):
        return
    sent = request.form.get('csrf_token', '')
    expected = session.get('csrf_token', '')
    if not expected or not compare_digest(str(sent), str(expected)):
        abort(400, 'Недійсний або відсутній CSRF-токен')


# ------------------------------------------------ IP-адреса та ліміти
def client_ip():
    """IP клієнта.

    За довіреним проксі (Render, nginx) адресу підставляє ProxyFix у
    request.remote_addr. Заголовок X-Forwarded-For напряму НЕ читаємо:
    клієнт може надіслати будь-яке значення й обійти обмеження частоти.
    """
    return request.remote_addr or 'unknown'


def _too_many(key, limit, window):
    now = time.time()
    recent = [t for t in _hits[key] if now - t < window]
    recent.append(now)
    _hits[key] = recent
    # прибираємо порожні записи, щоб словник не ріс безмежно
    for k in [k for k, v in _hits.items() if not v]:
        _hits.pop(k, None)
    return len(recent) > limit


def rate_limited(view):
    """Обмежує частоту звернень з однієї IP-адреси."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if _too_many('api:' + client_ip(), RATE_LIMIT, RATE_WINDOW):
            return jsonify({'error': 'Перевищено ліміт запитів, спробуйте пізніше',
                            'limit': RATE_LIMIT, 'window_seconds': RATE_WINDOW}), 429
        return view(*args, **kwargs)
    return wrapper


def login_rate_limited(view):
    """Обмежує кількість спроб входу - захист від перебору пароля."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if request.method == 'POST' and _too_many('login:' + client_ip(),
                                                  LOGIN_LIMIT, LOGIN_WINDOW):
            flash('Забагато спроб входу. Спробуйте пізніше.', 'error')
            return redirect(url_for('main.index')), 429
        return view(*args, **kwargs)
    return wrapper


def admin_required(view):
    """Дозволяє дію лише адміністратору.

    Якщо ADMIN_TOKEN не заданий, дія заблокована повністю - це безпечна
    поведінка за замовчуванням для публічного розгортання.
    """
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not admin_token():
            flash('Дію вимкнено: не задано ADMIN_TOKEN.', 'error')
            return redirect(url_for('main.index')), 403
        if not is_admin():
            flash('Потрібен вхід адміністратора.', 'error')
            return redirect(url_for('main.login', next=request.path)), 403
        return view(*args, **kwargs)
    return wrapper


def safe_next(value):
    """Повертає лише відносний шлях у межах цього сайту.

    Інакше зовнішнє посилання у параметрі next перетворило б сторінку входу
    на інструмент перенаправлення на чужий сайт (open redirect).
    """
    if not value or not value.startswith('/'):
        return None
    if value.startswith('//') or value.startswith('/\\'):
        return None
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return None
    return value


def mask_email(value):
    """Приховує адресу пошти у публічному інтерфейсі: o***@example.com"""
    if not value or '@' not in value:
        return value
    name, domain = value.split('@', 1)
    return (name[0] + '***' if name else '***') + '@' + domain
