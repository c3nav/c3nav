from django.apps import AppConfig


class EditorConfig(AppConfig):
    name = 'c3nav.editor'

    def ready(self):
        from c3nav.editor.hosters import init_hosters
        from c3nav.editor.forms import create_editor_forms
        init_hosters()
        create_editor_forms()
