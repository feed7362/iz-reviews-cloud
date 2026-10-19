# -*- coding: utf-8 -*-
"""Наповнення бази демонстраційними даними та аналіз їх модулем ШІ."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from app import db, ai  # noqa: E402

USERS = [('Олена Ковальчук', 'o.kovalchuk@example.com'),
         ('Андрій Мельник', 'a.melnyk@example.com'),
         ('Ірина Шевчук', 'i.shevchuk@example.com'),
         ('Максим Бондаренко', 'm.bondarenko@example.com')]

# (користувач, категорія, товар, оцінка, текст)
REVIEWS = [
    (0, 'Електроніка', 'Wireless headphones X200', 5,
     'Absolutely fantastic sound quality and the battery lasts all week. '
     'Comfortable even after hours of use. Best purchase I made this year.'),
    (1, 'Електроніка', 'Budget smartphone A3', 2,
     'The screen is dim, the camera is blurry and it freezes constantly. '
     'Terrible value for money, I regret buying it.'),
    (2, 'Книги', 'Clean Architecture', 5,
     'A brilliant and clearly written book. Every chapter gave me something '
     'practical to apply at work. Highly recommended for any developer.'),
    (3, 'Книги', 'Mystery of the Lost Key', 1,
     'Boring plot, flat characters and a predictable ending. '
     'I could not finish it, a complete waste of time.'),
    (0, 'Одяг', 'Running jacket Pro', 4,
     'Lightweight and keeps the wind out nicely. The zipper feels a bit cheap '
     'but overall I am happy with it.'),
    (1, 'Ігри', 'Space Colony Simulator', 5,
     'Addictive gameplay with a wonderful soundtrack. I lost track of time '
     'completely. The developers clearly cared about this project.'),
    (2, 'Ігри', 'Racing Legends 2024', 2,
     'Awful physics and the online mode disconnects every few minutes. '
     'Disappointing sequel to a great game.'),
    (3, 'Побутова техніка', 'Coffee machine Barista', 4,
     'Makes excellent coffee and is easy to clean. A little noisy in the '
     'morning but that is a minor issue.'),
    (0, 'Побутова техніка', 'Vacuum cleaner Turbo', 1,
     'Broke after two weeks of light use. Customer support was unhelpful '
     'and rude. Poor quality overall.'),
    (1, 'Одяг', 'Winter boots Nord', 5,
     'Warm, waterproof and surprisingly comfortable from the first day. '
     'Perfect for the cold season.'),
]

cats = {c['name']: c['id'] for c in db.list_categories()}
users = [db.upsert_user(n, e) for n, e in USERS]

created = analysed = 0
for ui, cat, product, rating, text in REVIEWS:
    existing = db.query('SELECT id FROM reviews WHERE product = %s AND user_id = %s',
                        (product, users[ui]['id']), one=True)
    if existing:
        rid = existing['id']
    else:
        rid = db.add_review(users[ui]['id'], cats[cat], product, text, rating)['id']
        created += 1
    res = ai.analyse(text)
    db.save_analysis(rid, res['sentiment'], res['confidence'], res['model'])
    analysed += 1
    print('%-32s %-5d %-9s %.3f' % (product[:32], rating, res['sentiment'], res['confidence']))

print()
print('Користувачів: %d | створено відгуків: %d | проаналізовано: %d'
      % (len(users), created, analysed))
s = db.stats()
print('Всього у базі:', dict(s['totals']))
