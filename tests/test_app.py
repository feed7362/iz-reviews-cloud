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
