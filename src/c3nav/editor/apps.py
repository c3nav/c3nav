from django.apps import AppConfig


class EditorConfig(AppConfig):
    name = 'c3nav.editor'

    def ready(self):
        from c3nav.editor.forms import create_editor_forms
        create_editor_forms()
