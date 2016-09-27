from django.apps import AppConfig


class EditorConfig(AppConfig):
    name = 'c3nav.editor'

    def ready(self):
        from c3nav.editor.hosters import init_hosters
        init_hosters()
