from collections import namedtuple
from importlib import import_module

from django.contrib.auth import get_user as auth_get_user
from django.contrib.auth.models import AnonymousUser
from django.db.models import Q
from ninja.security import HttpBearer

from c3nav import settings
from c3nav.api.exceptions import APIPermissionDenied, APITokenInvalid
from c3nav.api.schema import APIErrorSchema
from c3nav.control.models import UserPermissions

FakeRequest = namedtuple('FakeRequest', ('session', ))


description = """
An API token can be acquired in 4 ways:

* Use `anonymous` for guest access.
* Generate a session-bound token using the auth session endpoint.
* Create an API token in your user account settings.
* Create an API token by signing in through the auth endpoint.
""".strip()


class APITokenAuth(HttpBearer):
    openapi_name = "api token authentication"
    openapi_description = description

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
            user = auth_get_user(FakeRequest(session=session))
            return user
        elif token.startswith("secret:"):
            try:
                user_perms = UserPermissions.objects.filter(
                    ~Q(api_secret=""),
                    ~Q(api_secret__isnull=True),
                    api_secret=token.removeprefix("secret:")
                ).select_related("user").get()
            except UserPermissions.DoesNotExist:
                raise APITokenInvalid
            return user_perms.user
        # todo: implement token (app) auth
        raise APITokenInvalid

    def authenticate(self, request, token):
        user = self._authenticate(request, token)
        if self.logged_in and user.is_anonymous:
            raise APIPermissionDenied
        if self.superuser and not user.is_superuser:
            raise APIPermissionDenied
        return user


validate_responses = {422: APIErrorSchema, }
auth_responses = {401: APIErrorSchema, }
auth_permission_responses = {401: APIErrorSchema, 403: APIErrorSchema, }
