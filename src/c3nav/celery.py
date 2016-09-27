import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'c3nav.settings')

from django.conf import settings  # noqa

app = Celery('c3nav')
app.config_from_object('django.conf:settings')
app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)
