# -*- coding: utf-8 -*-
"""Тести вебзастосунку. Виконуються локально та у конвеєрі GitHub Actions."""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, ai, db  # noqa: E402


@pytest.fixture(scope='module')
def client():
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as c:
        yield c


# ------------------------------------------------------------- модуль ШІ
def test_local_model_positive():
    res = ai.analyse_local('This is wonderful, I absolutely love it!')
    assert res['sentiment'] == 'positive'
    assert 0.5 < res['confidence'] <= 1.0


def test_local_model_negative():
    res = ai.analyse_local('Terrible product, broke immediately, total waste of money.')
    assert res['sentiment'] == 'negative'
    assert 0.5 < res['confidence'] <= 1.0


def test_analyse_falls_back_without_token(monkeypatch):
    """Без токена Hugging Face має спрацювати локальна резервна модель."""
    monkeypatch.delenv('HF_API_TOKEN', raising=False)
    res = ai.analyse('An excellent and very enjoyable experience.')
    assert res['model'].startswith('local:')
    assert res['sentiment'] in {'positive', 'negative'}


def test_service_status_shape():
    st = ai.service_status()
    assert set(st) == {'hf_configured', 'hf_model', 'local_available'}
    assert st['local_available'] is True


# ------------------------------------------------------------------- API
def test_api_analyse_ok(client):
    r = client.post('/api/analyse', json={'text': 'Fantastic quality, very happy!'})
    assert r.status_code == 200
    data = r.get_json()
    assert data['sentiment'] in {'positive', 'negative'}
    assert 'model' in data


def test_api_analyse_rejects_short_text(client):
    r = client.post('/api/analyse', json={'text': 'ok'})
    assert r.status_code == 400
    assert 'error' in r.get_json()


# -------------------------------------------------------- схема бази даних
def test_schema_file_defines_all_tables():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'migrations', 'schema.sql')
    sql = open(path, encoding='utf-8').read().lower()
    for table in ('users', 'categories', 'reviews', 'analyses'):
        assert 'create table if not exists %s' % table in sql


def test_dsn_normalises_postgres_scheme(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgres://u:p@h:5432/d')
    assert db.dsn().startswith('postgresql://')


def test_dsn_requires_env(monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    with pytest.raises(RuntimeError):
        db.dsn()


# ------------------------------------------------------------ безпека
def token_of(client):
    """Отримує чинний CSRF-токен із сесії тестового клієнта."""
    client.get('/login')
    with client.session_transaction() as sess:
        return sess['csrf_token']


def post(client, path, **data):
    """POST із коректним CSRF-токеном - як це робить браузер із форми."""
    data['csrf_token'] = token_of(client)
    return client.post(path, data=data)


def test_mask_email():
    from app.security import mask_email
    assert mask_email('olena@example.com') == 'o***@example.com'
    assert mask_email('') == ''
    assert mask_email('not-an-email') == 'not-an-email'


def test_delete_requires_admin(client):
    """Видалення відгуку анонімним користувачем має бути заборонене."""
    assert post(client, '/review/1/delete').status_code == 403


def test_analyse_all_requires_admin(client):
    assert post(client, '/analyse-all').status_code == 403


def test_login_rejects_wrong_password(client, monkeypatch):
    monkeypatch.setenv('ADMIN_TOKEN', 'correct-token')
    r = post(client, '/login', password='wrong')
    assert r.status_code == 200          # лишаємось на сторінці входу
    with client.session_transaction() as sess:
        assert not sess.get('is_admin')


def test_login_accepts_correct_password(client, monkeypatch):
    monkeypatch.setenv('ADMIN_TOKEN', 'correct-token')
    r = post(client, '/login', password='correct-token')
    assert r.status_code == 302
    with client.session_transaction() as sess:
        assert sess.get('is_admin') is True
        sess.pop('is_admin', None)


def test_admin_disabled_without_token(client, monkeypatch):
    """Якщо ADMIN_TOKEN не заданий, вхід неможливий, а дії заблоковано."""
    monkeypatch.delenv('ADMIN_TOKEN', raising=False)
    assert post(client, '/login', password='').status_code == 200
    assert post(client, '/review/1/delete').status_code == 403


# --------------------------------------------- CSRF та відкрите перенаправлення
def test_safe_next_allows_relative_path():
    from app.security import safe_next
    assert safe_next('/dashboard') == '/dashboard'


def test_safe_next_blocks_external_and_tricks():
    from app.security import safe_next
    for bad in ('https://evil.example.com', '//evil.example.com',
                '/\\evil.example.com', 'http://evil', 'dashboard', '', None):
        assert safe_next(bad) is None


def test_post_without_csrf_token_rejected(client):
    """Форма без токена CSRF має відхилятися."""
    r = client.post('/login', data={'password': 'x'})
    assert r.status_code == 400


def test_post_with_csrf_token_accepted(client, monkeypatch):
    monkeypatch.setenv('ADMIN_TOKEN', 'tok')
    client.get('/login')                       # отримати токен у сесії
    with client.session_transaction() as sess:
        token = sess['csrf_token']
    r = client.post('/login', data={'password': 'tok', 'csrf_token': token})
    assert r.status_code == 302
    with client.session_transaction() as sess:
        sess.pop('is_admin', None)


def test_api_does_not_require_csrf(client):
    """JSON API не використовує куки сесії, тож токен там не потрібен."""
    r = client.post('/api/analyse', json={'text': 'Really good stuff here'})
    assert r.status_code in (200, 429)


# ---------------------------------------------- лічильники частоти запитів
def test_prune_removes_stale_keys():
    """Застарілі записи мають зникати: інакше словник ріс би безмежно."""
    import time as _t
    from app import security
    security._api_hits.clear()
    security._api_hits['api:1.2.3.4'] = [_t.time() - 99999]   # протермінований
    security._api_hits['api:5.6.7.8'] = [_t.time()]           # свіжий
    security._prune(security._api_hits, security.RATE_WINDOW, _t.time())
    assert 'api:1.2.3.4' not in security._api_hits
    assert 'api:5.6.7.8' in security._api_hits


def test_too_many_does_not_record():
    """Перевірка ліміту не має сама витрачати ліміт."""
    from app import security
    security._api_hits.clear()
    for _ in range(50):
        assert security.too_many('api:test', 5, 600) is False
    assert security._api_hits.get('api:test', []) == []


def test_successful_login_does_not_consume_limit(client, monkeypatch):
    """Вдалий вхід не наближає користувача до блокування."""
    from app import security
    monkeypatch.setenv('ADMIN_TOKEN', 'tok')
    security._login_hits.clear()
    for _ in range(3):
        r = post(client, '/login', password='tok')
        assert r.status_code == 302
    assert not security._login_hits
    with client.session_transaction() as sess:
        sess.pop('is_admin', None)


def test_failed_logins_eventually_block(client, monkeypatch):
    from app import security
    monkeypatch.setenv('ADMIN_TOKEN', 'tok')
    monkeypatch.setattr(security, 'LOGIN_LIMIT', 3)
    security._login_hits.clear()
    for _ in range(3):
        assert post(client, '/login', password='wrong').status_code == 200
    assert post(client, '/login', password='wrong').status_code == 429
    # навіть правильний пароль не приймається, поки діє блокування
    assert post(client, '/login', password='tok').status_code == 429
    security._login_hits.clear()


def test_api_flood_cannot_evict_login_counter(client, monkeypatch):
    """Потік запитів до API не має знімати блокування входу."""
    from app import security
    monkeypatch.setenv('ADMIN_TOKEN', 'tok')
    monkeypatch.setattr(security, 'LOGIN_LIMIT', 2)
    monkeypatch.setattr(security, 'MAX_KEYS', 5)
    security._login_hits.clear()
    security._api_hits.clear()
    for _ in range(2):
        post(client, '/login', password='wrong')
    assert post(client, '/login', password='wrong').status_code == 429
    # заповнюємо сховище API понад MAX_KEYS
    import time as _t
    for i in range(20):
        security._api_hits['api:10.0.0.%d' % i] = [_t.time()]
    assert post(client, '/login', password='wrong').status_code == 429
    security._login_hits.clear()
    security._api_hits.clear()


def test_ipv6_addresses_share_a_64_bucket():
    """Адреси однієї підмережі /64 мають потрапляти в один лічильник."""
    from app.security import client_ip
    from flask import Flask
    app = Flask(__name__)
    keys = set()
    for suffix in ('1', '2', 'dead:beef'):
        with app.test_request_context(environ_base={
                'REMOTE_ADDR': '2001:db8:abcd:1234::' + suffix}):
            keys.add(client_ip())
    assert len(keys) == 1
    with app.test_request_context(environ_base={'REMOTE_ADDR': '203.0.113.7'}):
        assert client_ip() == '203.0.113.7'
