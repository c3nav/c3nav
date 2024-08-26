from django.apps import AppConfig
from django.contrib.auth import user_logged_in
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save, pre_delete


class EditorConfig(AppConfig):
    name = 'c3nav.editor'

    def ready(self):
        from c3nav.editor.signals import set_changeset_author_on_login
        from c3nav.editor import overlay
        pre_save.connect(overlay.handle_pre_change_instance)
        pre_delete.connect(overlay.handle_pre_change_instance)
        post_save.connect(overlay.handle_post_save)
        post_delete.connect(overlay.handle_post_delete)
        m2m_changed.connect(overlay.handle_m2m_changed)
        user_logged_in.connect(set_changeset_author_on_login)
