# -*- coding: utf-8 -*-
"""Навчання локальної моделі визначення тональності та збереження у файл.

Модель використовується вебзастосунком як офлайн-резерв, коли хмарний сервіс
Hugging Face недоступний. Архітектура та набір даних - ті самі, що в ЛР7.
"""
import io
import os
import time
import pandas as pd
import joblib
from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.metrics import accuracy_score, classification_report

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(os.path.dirname(ROOT), 'lab7', 'data', 'IMDB-Dataset.csv')
OUT = os.path.join(ROOT, 'app', 'model')
os.makedirs(OUT, exist_ok=True)
log = io.open(os.path.join(ROOT, 'output', '01-model-training.txt'), 'w', encoding='utf-8')


def say(s=''):
    print(s)
    log.write(s + '\n')


df = pd.read_csv(CSV).drop_duplicates(subset='review').reset_index(drop=True)
df['review'] = df['review'].str.replace('<br />', ' ', regex=False)
say('Набір даних: IMDB Dataset of 50K Movie Reviews')
say('Після очищення: %d відгуків, позитивних %d, негативних %d'
    % (len(df), (df.sentiment == 'positive').sum(), (df.sentiment == 'negative').sum()))

X_train, X_test, y_train, y_test = train_test_split(
    df['review'], df['sentiment'], test_size=0.2, random_state=42, stratify=df['sentiment'])

pipe = Pipeline([
    ('tfidf', TfidfVectorizer(max_features=50000, ngram_range=(1, 2),
                              stop_words='english', sublinear_tf=True)),
    ('clf', LogisticRegression(max_iter=1000, C=2.0)),
])
t0 = time.time()
pipe.fit(X_train, y_train)
say('Навчання завершено за %.1f с' % (time.time() - t0))

pred = pipe.predict(X_test)
acc = accuracy_score(y_test, pred)
say('Accuracy на тестовій вибірці: %.4f' % acc)
say('')
say(classification_report(y_test, pred, digits=4))

path = os.path.join(OUT, 'sentiment_tfidf.joblib')
joblib.dump(pipe, path, compress=3)
say('Модель збережено: %s (%.1f МБ)' % (path, os.path.getsize(path) / 1048576))

samples = ['Absolutely loved this, would buy again!',
           'Terrible quality, broke after one day.',
           'It works, nothing special.']
say('')
say('Перевірка на прикладах:')
for s in samples:
    pr = pipe.predict_proba([s])[0]
    say('  %-9s %.3f  %s' % (pipe.classes_[pr.argmax()], pr.max(), s))
log.close()
