from django.conf import settings
from ninja import Router as APIRouter
from ninja import Schema

from c3nav.api.newauth import APIAuthMethod, auth_responses
from c3nav.api.utils import NonEmptyStr
from c3nav.control.models import UserPermissions

auth_api_router = APIRouter(tags=["auth"])


class AuthStatusSchema(Schema):
    """
    Current auth state and permissions
    """
    method: APIAuthMethod
    readonly: bool
    scopes: list[str]


@auth_api_router.get('/status/', summary="get current auth details",
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
    """
    An API token to be used with Bearer authentication
    """
    token: NonEmptyStr


@auth_api_router.get('/session/', response=APITokenSchema, auth=None,
                     summary="Get API token tied to the current session")
def session_token(request):
    session_id = request.COOKIES.get(settings.SESSION_COOKIE_NAME, None)
    return {"token": "anonymous" if session_id is None else f"session:{session_id}"}
