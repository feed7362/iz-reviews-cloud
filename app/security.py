# -*- coding: utf-8 -*-
"""Захист застосунку: доступ адміністратора та обмеження частоти запитів.

Застосунок розгортається у публічній хмарі, тому дії, які змінюють дані або
витрачають квоту платного сервісу ШІ, не можуть бути доступні анонімно.
"""
import os
import time
from collections import defaultdict
from functools import wraps
from hmac import compare_digest

from flask import session, request, redirect, url_for, flash, jsonify

# Проста пам'ять лічильників. Достатньо для одного процесу gunicorn;
# для кількох робітників потрібне спільне сховище (наприклад Redis).
_hits = defaultdict(list)

RATE_LIMIT = int(os.environ.get('RATE_LIMIT', '20'))        # запитів
RATE_WINDOW = int(os.environ.get('RATE_WINDOW', '600'))     # за секунд


def admin_token():
    return os.environ.get('ADMIN_TOKEN', '')


def is_admin():
    return bool(session.get('is_admin'))


def check_password(value):
    token = admin_token()
    if not token:
        return False
    return compare_digest(str(value), token)


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


def rate_limited(view):
    """Обмежує частоту звернень з однієї IP-адреси."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        ip = (request.headers.get('X-Forwarded-For', request.remote_addr or '?')
              .split(',')[0].strip())
        now = time.time()
        recent = [t for t in _hits[ip] if now - t < RATE_WINDOW]
        if len(recent) >= RATE_LIMIT:
            recent.append(now)
            _hits[ip] = recent
            return jsonify({'error': 'Перевищено ліміт запитів, спробуйте пізніше',
                            'limit': RATE_LIMIT, 'window_seconds': RATE_WINDOW}), 429
        recent.append(now)
        _hits[ip] = recent
        return view(*args, **kwargs)
    return wrapper


def mask_email(value):
    """Приховує адресу пошти у публічному інтерфейсі: o***@example.com"""
    if not value or '@' not in value:
        return value
    name, domain = value.split('@', 1)
    return (name[0] + '***' if name else '***') + '@' + domain
