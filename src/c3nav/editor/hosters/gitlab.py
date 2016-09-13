from .base import Hoster


class GitlabHoster(Hoster):
    def __init__(self, app_id, app_secret, **kwargs):
        super().__init__(**kwargs)
        self._app_id = app_id
        self._app_secret = app_secret
