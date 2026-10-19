# -*- coding: utf-8 -*-
"""Точка входу для сервера WSGI (gunicorn) та локального запуску."""
import os
from dotenv import load_dotenv

load_dotenv()

from app import create_app          # noqa: E402  (після load_dotenv)
from app.db import init_schema      # noqa: E402

application = create_app()
app = application

# У хмарі схема застосовується автоматично під час першого запуску.
if os.environ.get('AUTO_INIT_DB', '1') == '1':
    try:
        init_schema()
    except Exception as exc:                       # noqa: BLE001
        print('init_schema пропущено:', type(exc).__name__, exc)

if __name__ == '__main__':
    if os.environ.get('INIT_DB') == '1':
        init_schema()
        print('Схему бази даних застосовано')
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', 5000)), debug=True)
