-- Індивідуальне завдання: вебзастосунок «Аналіз відгуків»
-- Схема реляційної бази даних PostgreSQL.
--   Таблиці users, categories, reviews      - індивідуальне завдання 1
--   Таблиця  analyses                        - індивідуальне завдання 2 (модуль ШІ)

CREATE TABLE IF NOT EXISTS users (
    id         SERIAL PRIMARY KEY,
    name       VARCHAR(80)  NOT NULL,
    email      VARCHAR(120) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS categories (
    id   SERIAL PRIMARY KEY,
    name VARCHAR(60) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS reviews (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    product     VARCHAR(120) NOT NULL,
    body        TEXT         NOT NULL CHECK (length(body) >= 10),
    rating      SMALLINT     NOT NULL CHECK (rating BETWEEN 1 AND 5),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Результат роботи модуля штучного інтелекту (ІЗ2).
-- Один відгук аналізується один раз; повторний аналіз оновлює запис.
CREATE TABLE IF NOT EXISTS analyses (
    id          SERIAL PRIMARY KEY,
    review_id   INTEGER NOT NULL UNIQUE REFERENCES reviews(id) ON DELETE CASCADE,
    sentiment   VARCHAR(10)   NOT NULL CHECK (sentiment IN ('positive', 'negative')),
    confidence  NUMERIC(5, 4) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    model_name  VARCHAR(80)   NOT NULL,
    analyzed_at TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_reviews_category ON reviews(category_id);
CREATE INDEX IF NOT EXISTS idx_reviews_created  ON reviews(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analyses_review  ON analyses(review_id);

INSERT INTO categories (name) VALUES
    ('Електроніка'), ('Книги'), ('Одяг'), ('Ігри'), ('Побутова техніка')
ON CONFLICT (name) DO NOTHING;
