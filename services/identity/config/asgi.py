"""ASGI entrypoint for the Identity service.

Identity is request/response and normally served via gunicorn/WSGI, but ASGI is
provided for uniformity and future async needs.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_asgi_application()
