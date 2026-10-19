# -*- coding: utf-8 -*-
"""Модуль штучного інтелекту: визначення тональності відгуку (ІЗ2).

Основний канал - хмарний сервіс Hugging Face Inference API.
Резервний - власна модель (TF-IDF + логістична регресія), навчена в ЛР7
і збережена у файл; використовується, коли токен не задано або сервіс
недоступний. Це дозволяє застосунку працювати без зовнішніх залежностей.
"""
import os
import joblib
import requests

HF_MODEL = os.environ.get('HF_MODEL', 'distilbert-base-uncased-finetuned-sst-2-english')
HF_URL = 'https://api-inference.huggingface.co/models/' + HF_MODEL
HF_TIMEOUT = float(os.environ.get('HF_TIMEOUT', '12'))
LOCAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'model', 'sentiment_tfidf.joblib')

_local = None


def _local_model():
    # joblib.load виконує код з файлу, тому завантажувати можна лише довірений
    # файл. Тут це власний артефакт, створений scripts/train_model.py і
    # збережений у репозиторії разом із застосунком; зовнішні файли сюди не
    # потрапляють.
    global _local
    if _local is None:
        _local = joblib.load(LOCAL_PATH)
    return _local


def analyse_local(text):
    pipe = _local_model()
    proba = pipe.predict_proba([text])[0]
    idx = proba.argmax()
    return {'sentiment': pipe.classes_[idx],
            'confidence': float(proba[idx]),
            'model': 'local: TF-IDF + LogisticRegression'}


def analyse_hf(text):
    """Запит до хмарного сервісу. Повертає None, якщо сервіс недоступний."""
    token = os.environ.get('HF_API_TOKEN')
    if not token:
        return None
    try:
        r = requests.post(HF_URL,
                          headers={'Authorization': 'Bearer ' + token},
                          json={'inputs': text[:2000],
                                'options': {'wait_for_model': True}},
                          timeout=HF_TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
        # Відповідь: [[{'label': 'POSITIVE', 'score': 0.99}, {...}]]
        scores = data[0] if isinstance(data[0], list) else data
        best = max(scores, key=lambda d: d['score'])
        return {'sentiment': 'positive' if best['label'].upper().startswith('POS')
                             else 'negative',
                'confidence': float(best['score']),
                'model': 'Hugging Face: ' + HF_MODEL}
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None


def analyse(text, allow_cloud=True):
    """Аналіз тональності: спершу хмарний сервіс, за потреби - власна модель.

    allow_cloud=False змушує одразу використати локальну модель. Так
    застосунок поводиться, коли вичерпано сукупний бюджет звернень до
    платного API: результат усе одно надається, лише дешевшою моделлю.
    """
    if allow_cloud:
        result = analyse_hf(text)
        if result:
            return result
    return analyse_local(text)


def service_status():
    return {'hf_configured': bool(os.environ.get('HF_API_TOKEN')),
            'hf_model': HF_MODEL,
            'local_available': os.path.exists(LOCAL_PATH)}
