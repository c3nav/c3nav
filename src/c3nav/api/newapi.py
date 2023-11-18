from django.conf import settings
from ninja import Router as APIRouter
from ninja import Schema

from c3nav.api.utils import NonEmptyStr

auth_api_router = APIRouter(tags=["auth"])


class APITokenSchema(Schema):
    """
    An API token to be used with Bearer authentication
    """
    token: NonEmptyStr


@auth_api_router.get('/session/', response=APITokenSchema, auth=None,
                     summary="Get session API token")
def session_token(request):
    session_id = request.COOKIES.get(settings.SESSION_COOKIE_NAME, None)
    return {"token": "anonymous" if session_id is None else f"session:{session_id}"}
