# -*- coding: utf-8 -*-
"""Вебзастосунок «Аналіз відгуків» (Flask).

ІЗ1: клієнт-серверна частина, обробка запитів, віддалена БД PostgreSQL.
ІЗ2: модуль штучного інтелекту, візуалізація результатів.
"""
import os
from flask import Flask


def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
    app.config['JSON_AS_ASCII'] = False

    from . import routes
    app.register_blueprint(routes.bp)

    @app.context_processor
    def inject():
        return {'app_title': 'Аналіз відгуків'}

    return app
