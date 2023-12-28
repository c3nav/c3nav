from django.core.handlers.wsgi import WSGIRequest
from ninja import Field as APIField
from ninja import Router as APIRouter

from c3nav.api.auth import APIKeyType, auth_responses
from c3nav.api.exceptions import APIRequestDontUseAPIKey
from c3nav.api.schema import BaseSchema
from c3nav.api.utils import NonEmptyStr
from c3nav.control.models import UserPermissions

auth_api_router = APIRouter(tags=["auth"])


class AuthStatusSchema(BaseSchema):
    """
    Current auth state and permissions
    """
    key_type: APIKeyType = APIField(
        title="api key type",
        description="the type of api key that is being used"
    )
    readonly: bool = APIField(
        title="read only",
        description="if true, no API operations that modify data can be called"
    )
    scopes: list[str] = APIField(
        title="authorized scopes",
        description="scopes available with the current authorization",
    )


@auth_api_router.get('/status/', summary="get status",
                     description="Returns details about the current authentication",
                     response={200: AuthStatusSchema, **auth_responses})
def get_status(request):
    permissions = UserPermissions.get_for_user(request.user)
    scopes = [
        *(p for p in ("editor_access", "grant_permissions", "mesh_control") if getattr(permissions, p)),
        *([] if request.auth.readonly else ["write"]),
    ]
    return AuthStatusSchema(
        method=request.auth.method,
        readonly=request.auth.readonly,
        scopes=scopes,
    )


class APIKeySchema(BaseSchema):
    key: NonEmptyStr = APIField(
        title="API key",
        description="API secret to be directly used with `X-API-Key` HTTP header."
    )


@auth_api_router.get('/session/', response=APIKeySchema, auth=None,
                     summary="get session-bound key")
def session_key(request: WSGIRequest):
    """
    Get an API key that is bound to the transmitted session cookie, or a newly created session cookie if none is sent.

    Keep in mind that this API key will be invalid if the session gets signed out or similar.
    """
    if 'x-api-key' in request.headers:
        raise APIRequestDontUseAPIKey()
    if request.session.session_key is None:
        request.session.create()
    return {"key": f"session:{request.session.session_key}"}
