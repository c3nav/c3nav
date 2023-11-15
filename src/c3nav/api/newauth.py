from importlib import import_module

from django.contrib.auth.models import AnonymousUser
from django.db.models import Q
from ninja.security import HttpBearer

from c3nav import settings
from c3nav.api.exceptions import APITokenInvalid, APIPermissionDenied
from c3nav.api.schema import APIErrorSchema
from c3nav.control.models import UserPermissions


class InvalidToken(Exception):
    pass


class BearerAuth(HttpBearer):
    def __init__(self, logged_in=False, superuser=False):
        super().__init__()
        self.logged_in = superuser or logged_in
        self.superuser = superuser
        engine = import_module(settings.SESSION_ENGINE)
        self.SessionStore = engine.SessionStore

    def _authenticate(self, request, token):
        if token == "anonymous":
            return AnonymousUser
        elif token.startswith("session:"):
            session = self.SessionStore(token.removeprefix("session:"))
            # todo: ApiTokenInvalid?
            return session.user
        elif token.startswith("secret:"):
            try:
                user_perms = UserPermissions.objects.filter(
                    ~Q(api_secret=""),
                    ~Q(api_secret__isnull=True),
                    api_secret=token.removeprefix("secret:")
                ).select_related("user").get()
            except UserPermissions.DoesNotExist:
                raise APITokenInvalid
            session = self.SessionStore(token.removeprefix("secret:"))
            return session.user
        # todo: implement token (app) auth
        raise APITokenInvalid

    def authenticate(self, request, token):
        user = self._authenticate(request, token)
        if self.logged_in and user.is_anonymous:
            raise APIPermissionDenied
        if self.superuser and not user.is_superuser:
            raise APIPermissionDenied
        return user


auth_responses = {401: APIErrorSchema}
auth_permission_responses = {401: APIErrorSchema, 403: APIErrorSchema}

