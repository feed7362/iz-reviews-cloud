# -*- coding: utf-8 -*-
"""Вебзастосунок «Аналіз відгуків» (Flask).

ІЗ1: клієнт-серверна частина, обробка запитів, віддалена БД PostgreSQL.
ІЗ2: модуль штучного інтелекту, візуалізація результатів.
"""
import os
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix


def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
    app.config['JSON_AS_ASCII'] = False

    # Куки сесії: недоступні для JavaScript, не надсилаються при переходах
    # з інших сайтів (захист від CSRF), лише через HTTPS у хмарі.
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FORCE_HTTPS', '0') == '1'

    # У хмарі застосунок працює за зворотним проксі: він підставляє справжню
    # IP-адресу клієнта у request.remote_addr (один довірений вузол).
    if os.environ.get('BEHIND_PROXY', '0') == '1':
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    from . import routes
    from .security import mask_email, is_admin, csrf_token, validate_csrf
    app.register_blueprint(routes.bp)
    app.jinja_env.filters['mask_email'] = mask_email
    app.before_request(validate_csrf)

    @app.context_processor
    def inject():
        return {'app_title': 'Аналіз відгуків',
                'is_admin': is_admin(),
                'csrf_token': csrf_token}

    return app
