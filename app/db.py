# -*- coding: utf-8 -*-
"""Підключення до віддаленої бази даних PostgreSQL та доступ до даних."""
import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager

SCHEMA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'migrations', 'schema.sql')


def dsn():
    """Рядок підключення береться з DATABASE_URL (так його задає хмарний хостинг)."""
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise RuntimeError('Не задано змінну середовища DATABASE_URL')
    # Деякі провайдери віддають схему postgres://, якої psycopg2 не приймає
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    return url


@contextmanager
def connect():
    cn = psycopg2.connect(dsn(), cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield cn
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cn.close()


def init_schema():
    """Створює таблиці, якщо їх ще немає."""
    with open(SCHEMA, encoding='utf-8') as f:
        sql = f.read()
    with connect() as cn, cn.cursor() as cur:
        cur.execute(sql)


def query(sql, params=None, one=False):
    with connect() as cn, cn.cursor() as cur:
        cur.execute(sql, params or ())
        if cur.description is None:
            return None
        rows = cur.fetchall()
        return (rows[0] if rows else None) if one else rows


def execute(sql, params=None, returning=False):
    with connect() as cn, cn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchone() if returning else cur.rowcount


# ----------------------------------------------------------------- користувачі
def upsert_user(name, email):
    """Повертає користувача за email, створюючи його за потреби.

    Ім'я існуючого користувача НЕ перезаписується: форма анонімна, тож інакше
    будь-хто міг би змінити ім'я чужого облікового запису, вказавши його пошту.
    Конструкція DO UPDATE SET email = EXCLUDED.email - навмисна «порожня»
    зміна, потрібна лише щоб RETURNING повернув наявний рядок.
    """
    return execute(
        """INSERT INTO users (name, email) VALUES (%s, %s)
           ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email
           RETURNING id, name, email""",
        (name.strip(), email.strip().lower()), returning=True)


def list_categories():
    return query('SELECT id, name FROM categories ORDER BY name')


# --------------------------------------------------------------------- відгуки
def add_review(user_id, category_id, product, body, rating):
    return execute(
        """INSERT INTO reviews (user_id, category_id, product, body, rating)
           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
        (user_id, category_id, product.strip(), body.strip(), rating), returning=True)


REVIEW_SELECT = """
SELECT r.id, r.product, r.body, r.rating, r.created_at,
       u.name AS user_name, u.email,
       c.name AS category,
       a.sentiment, a.confidence, a.model_name, a.analyzed_at
FROM reviews r
JOIN users u      ON u.id = r.user_id
JOIN categories c ON c.id = r.category_id
LEFT JOIN analyses a ON a.review_id = r.id
"""


def list_reviews(category_id=None, sentiment=None, limit=100):
    where, params = [], []
    if category_id:
        where.append('r.category_id = %s')
        params.append(category_id)
    if sentiment == 'none':
        where.append('a.id IS NULL')
    elif sentiment:
        where.append('a.sentiment = %s')
        params.append(sentiment)
    sql = REVIEW_SELECT + ('WHERE ' + ' AND '.join(where) if where else '')
    sql += ' ORDER BY r.created_at DESC LIMIT %s'
    params.append(limit)
    return query(sql, params)


def get_review(review_id):
    return query(REVIEW_SELECT + 'WHERE r.id = %s', (review_id,), one=True)


def delete_review(review_id):
    return execute('DELETE FROM reviews WHERE id = %s', (review_id,))


# ------------------------------------------------- результати аналізу ШІ (ІЗ2)
def save_analysis(review_id, sentiment, confidence, model_name):
    return execute(
        """INSERT INTO analyses (review_id, sentiment, confidence, model_name)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (review_id) DO UPDATE
             SET sentiment = EXCLUDED.sentiment,
                 confidence = EXCLUDED.confidence,
                 model_name = EXCLUDED.model_name,
                 analyzed_at = now()
           RETURNING id""",
        (review_id, sentiment, round(float(confidence), 4), model_name), returning=True)


def unanalysed_reviews(limit=50):
    return query("""SELECT r.id, r.body FROM reviews r
                    LEFT JOIN analyses a ON a.review_id = r.id
                    WHERE a.id IS NULL ORDER BY r.id LIMIT %s""", (limit,))


# ----------------------------------------------------------------- статистика
def stats():
    totals = query("""
        SELECT (SELECT count(*) FROM reviews)  AS reviews,
               (SELECT count(*) FROM users)    AS users,
               (SELECT count(*) FROM analyses) AS analysed,
               (SELECT round(avg(rating), 2) FROM reviews) AS avg_rating""", one=True)
    by_sentiment = query("""SELECT sentiment, count(*) AS n
                            FROM analyses GROUP BY sentiment ORDER BY sentiment""")
    by_category = query("""
        SELECT c.name AS category, count(r.id) AS n,
               count(*) FILTER (WHERE a.sentiment = 'positive') AS positive,
               count(*) FILTER (WHERE a.sentiment = 'negative') AS negative,
               round(avg(r.rating), 2) AS avg_rating
        FROM categories c
        LEFT JOIN reviews r  ON r.category_id = c.id
        LEFT JOIN analyses a ON a.review_id = r.id
        GROUP BY c.name ORDER BY n DESC, c.name""")
    return {'totals': totals, 'by_sentiment': by_sentiment, 'by_category': by_category}
