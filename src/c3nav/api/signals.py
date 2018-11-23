def remove_tokens_on_user_save(sender, instance, **kwargs):
    instance.login_tokens.exclude(session_auth_hash=instance.get_session_auth_hash()).delete()
