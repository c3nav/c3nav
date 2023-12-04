from django.conf import settings
from ninja import Field as APIField
from ninja import Router as APIRouter
from ninja import Schema

from c3nav.api.auth import APIKeyType, auth_responses
from c3nav.api.utils import NonEmptyStr
from c3nav.control.models import UserPermissions

auth_api_router = APIRouter(tags=["auth"])


class AuthStatusSchema(Schema):
    """
    Current auth state and permissions
    """
    key_type: APIKeyType = APIField(
        title="api key type",
        description="the type of api KEY THAT IS BEING USED"
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


class APITokenSchema(Schema):
    token: NonEmptyStr = APIField(
        title="API token",
        description="API token to be directly used with `Authorization: Bearer <token>` HTTP header."
    )


@auth_api_router.get('/session/', response=APITokenSchema, auth=None,
                     summary="get session-bound token")
def session_token(request):
    """
    Get an API token that is bound to the transmitted session cookie.

    Keep in mind that this API token will be invalid if the session gets signed out or similar.
    """
    session_id = request.COOKIES.get(settings.SESSION_COOKIE_NAME, None)
    return {"token": "anonymous" if session_id is None else f"session:{session_id}"}
