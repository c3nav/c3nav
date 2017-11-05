from django.apps import AppConfig
from django.db.models.signals import m2m_changed, post_delete, post_save


class EditorConfig(AppConfig):
    name = 'c3nav.editor'

    def ready(self):
        from c3nav.editor.models import ChangeSet
        post_save.connect(ChangeSet.object_changed_handler)
        post_delete.connect(ChangeSet.object_changed_handler)
        m2m_changed.connect(ChangeSet.object_changed_handler)
