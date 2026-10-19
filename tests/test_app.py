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
