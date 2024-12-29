from collections import namedtuple
from dataclasses import dataclass
from enum import StrEnum
from importlib import import_module

from django.contrib.auth import get_user as auth_get_user
from django.contrib.auth.models import AnonymousUser
from django.utils.functional import SimpleLazyObject, lazy
from ninja.security import APIKeyHeader

from c3nav import settings
from c3nav.api.exceptions import APIKeyInvalid, APIPermissionDenied
from c3nav.api.models import Secret
from c3nav.api.schema import APIErrorSchema
from c3nav.control.middleware import UserPermissionsMiddleware
from c3nav.control.models import UserPermissions

FakeRequest = namedtuple('FakeRequest', ('session', ))


class APIKeyType(StrEnum):
    ANONYMOUS = 'anonymous'
    SESSION = 'session'
    SECRET = 'secret'


@dataclass
class APIAuthDetails:
    key_type: APIKeyType
    readonly: bool


description = """
An API key can be acquired in 4 ways:

* Use `anonymous` for guest access.
* Generate a session-bound temporary key using the auth session endpoint.
* Create an API secret in your user account settings.
""".strip()


class APIKeyAuth(APIKeyHeader):
    param_name = "X-API-Key"

    openapi_name = "api key authentication"
    openapi_description = description

    def __init__(self, logged_in=False, superuser=False, permissions: set[str] = None, is_readonly=False):
        super().__init__()
        self.logged_in = superuser or logged_in
        self.superuser = superuser
        self.permissions = permissions or set()
        self.is_readonly = is_readonly
        engine = import_module(settings.SESSION_ENGINE)
        self.SessionStore = engine.SessionStore

    def _authenticate(self, request, key) -> APIAuthDetails:
        request.user = AnonymousUser()
        request.user_permissions = SimpleLazyObject(lambda: UserPermissionsMiddleware.get_user_permissions(request))
        request.user_space_accesses = lazy(UserPermissionsMiddleware.get_user_space_accesses, dict)(request)

        if key is None:
            raise APIKeyInvalid

        if key == "anonymous":
            return APIAuthDetails(
                key_type=APIKeyType.ANONYMOUS,
                readonly=True,
            )
        elif key.startswith("session:"):
            session = self.SessionStore(key.removeprefix("session:"))
            user = auth_get_user(FakeRequest(session=session))
            request.user = user
            return APIAuthDetails(
                key_type=APIKeyType.SESSION,
                readonly=False,
            )
        elif key.startswith("secret:"):
            try:
                secret = Secret.objects.get_by_secret(key.removeprefix("secret:")).get()
            except Secret.DoesNotExist:
                raise APIKeyInvalid

            # get user permissions and restrict them based on scopes
            user_permissions: UserPermissions = UserPermissions.get_for_user(secret.user)
            if secret.scope_mesh is False:
                user_permissions.mesh_control = False
            if secret.scope_editor is False:
                user_permissions.editor_access = False
            if secret.scope_grant_permissions is False:
                user_permissions.grant_permissions = False
            if secret.scope_load is False:
                user_permissions.can_write_laod_data = False

            request.user = secret.user
            request.user_permissions = user_permissions

            return APIAuthDetails(
                key_type=APIKeyType.SESSION,
                readonly=secret.readonly
            )
        raise APIKeyInvalid

    def authenticate(self, request, key):
        auth_result = self._authenticate(request, key)
        if self.logged_in and not request.user.is_authenticated:
            raise APIPermissionDenied('You need to be signed in for this request.')
        if self.superuser and not request.user.is_superuser:
            raise APIPermissionDenied('You need to have admin rights for this endpoint.')
        for permission in self.permissions:
            if not getattr(request.user_permissions, permission):
                raise APIPermissionDenied('You need to have the "%s" permission for this endpoint.' % permission)
        if request.method == 'GET' and self.is_readonly:
            raise ValueError('this makes no sense for GET')
        if request.method != 'GET' and not self.is_readonly and auth_result.readonly:
            raise APIPermissionDenied('You need a non-readonly API access key for this endpoint.')
        return auth_result


validate_responses = {422: APIErrorSchema, }
auth_responses = {401: APIErrorSchema, }
auth_permission_responses = {401: APIErrorSchema, 403: APIErrorSchema, }
