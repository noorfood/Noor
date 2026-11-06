"""WSGI entrypoint for the Noor Foods rebuild (Render).

Release-approved 2026-11-06: the development-only guard that blocked
deployment was removed when the user decided to go live on Render.
"""
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'noor_foods.settings')

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
