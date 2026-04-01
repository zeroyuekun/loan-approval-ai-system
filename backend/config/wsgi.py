"""
WSGI config for loan approval AI system.

It exposes the WSGI callable as a module-level variable named ``application``.
"""

import os

from dotenv import load_dotenv
from django.core.wsgi import get_wsgi_application

load_dotenv()
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

application = get_wsgi_application()
