from django.apps import AppConfig


class EditorConfig(AppConfig):
    name = 'c3nav.editor'

    def ready(self):
        from .hosters import init_hosters
        init_hosters()
