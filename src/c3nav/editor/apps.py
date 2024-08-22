from django.apps import AppConfig
from django.contrib.auth import user_logged_in
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save, pre_delete

from c3nav.editor import changes


class EditorConfig(AppConfig):
    name = 'c3nav.editor'

    def ready(self):
        from c3nav.editor.signals import set_changeset_author_on_login
        pre_save.connect(changes.handle_pre_change_instance)
        pre_delete.connect(changes.handle_pre_change_instance)
        post_save.connect(changes.handle_post_save)
        post_delete.connect(changes.handle_post_delete)
        m2m_changed.connect(changes.handle_m2m_changed)
        user_logged_in.connect(set_changeset_author_on_login)
