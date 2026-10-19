# -*- coding: utf-8 -*-
"""Захист застосунку: доступ адміністратора, CSRF та обмеження частоти запитів.

Застосунок розгортається у публічній хмарі, тому дії, які змінюють дані або
витрачають квоту платного сервісу ШІ, не можуть бути доступні анонімно.
"""
import ipaddress
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
#
# Лічильники входу зберігаються ОКРЕМО від лічильників API: інакше потік
# звернень до API міг би витіснити запис про невдалі входи й зняти блокування.
_api_hits = defaultdict(list)
_login_hits = defaultdict(list)
_hits = _api_hits          # сумісність зі старими тестами

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
MAX_KEYS = int(os.environ.get('RATE_MAX_KEYS', '10000'))


def client_ip():
    """Ключ клієнта для лічильників.

    За довіреним проксі адресу підставляє ProxyFix у request.remote_addr.
    Заголовок X-Forwarded-For напряму НЕ читаємо: клієнт може надіслати
    будь-яке значення й обійти обмеження.

    Адреси IPv6 групуються за префіксом /64, бо один господар зазвичай
    розпоряджається цілою такою підмережею. Без цього досить було б міняти
    адресу в межах власної /64, щоб щоразу діставати свіжий лічильник.

    Увага: якщо застосунок стоїть за проксі, але BEHIND_PROXY не ввімкнено,
    remote_addr буде адресою проксі - спільною для всіх користувачів. Тому
    у хмарі BEHIND_PROXY=1 обов'язковий (задано у render.yaml).
    """
    raw = request.remote_addr or 'unknown'
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return raw
    if addr.version == 6:
        net = ipaddress.ip_network(f'{raw}/64', strict=False)
        return str(net.network_address) + '/64'
    return raw


def _prune(store, window, now):
    """Прибирає записи, старші за вікно.

    Раніше тут видалялися порожні списки, яких ніколи не було: запис завжди
    містив щонайменше одну свіжу мітку часу, тож словник ріс безмежно.
    """
    stale = [k for k, v in store.items() if not v or now - v[-1] > window]
    for k in stale:
        store.pop(k, None)


def _check(store, key, limit, window):
    """Чи вичерпано ліміт. Нічого не записує.

    Якщо сховище переповнене живими записами, новий ключ вважається
    обмеженим (відмова на користь безпеки) - записи в межах вікна не
    витісняються. Інакше зловмисник міг би заповнити сховище й у такий
    спосіб скинути чужий (або власний) лічильник.
    """
    now = time.time()
    _prune(store, window, now)
    recent = [t for t in store.get(key, []) if now - t < window]
    if recent:
        store[key] = recent
    if key not in store and len(store) >= MAX_KEYS:
        return True
    return len(recent) >= limit


def _record(store, key, window):
    now = time.time()
    _prune(store, window, now)
    if key not in store and len(store) >= MAX_KEYS:
        return                      # сховище заповнене живими записами
    store[key].append(now)


def too_many(key, limit, window):
    """Перевірка ліміту API (залишено для сумісності з тестами)."""
    return _check(_api_hits, key, limit, window)


def record_attempt(key):
    _record(_api_hits, key, RATE_WINDOW)


def rate_limited(view):
    """Обмежує частоту звернень з однієї адреси."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        key = 'api:' + client_ip()
        if _check(_api_hits, key, RATE_LIMIT, RATE_WINDOW):
            return jsonify({'error': 'Перевищено ліміт запитів, спробуйте пізніше',
                            'limit': RATE_LIMIT, 'window_seconds': RATE_WINDOW}), 429
        _record(_api_hits, key, RATE_WINDOW)
        return view(*args, **kwargs)
    return wrapper


def login_blocked():
    """Чи вичерпано ліміт НЕВДАЛИХ спроб входу з цієї адреси.

    Рахуємо лише невдалі спроби: інакше користувач, який просто кілька разів
    заходив правильно, витрачав би власний ліміт.
    """
    return _check(_login_hits, 'login:' + client_ip(), LOGIN_LIMIT, LOGIN_WINDOW)


def record_failed_login():
    _record(_login_hits, 'login:' + client_ip(), LOGIN_WINDOW)


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
