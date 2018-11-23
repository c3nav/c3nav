from django.apps import AppConfig
from django.conf import settings
from django.db.models.signals import post_save


class APIConfig(AppConfig):
    name = 'c3nav.api'

    def ready(self):
        from c3nav.api.signals import remove_tokens_on_user_save
        post_save.connect(remove_tokens_on_user_save, sender=settings.AUTH_USER_MODEL)
