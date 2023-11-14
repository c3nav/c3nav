from django.conf import settings
from ninja import Router as APIRouter
from ninja import Schema

auth_api_router = APIRouter(tags=["auth"])


class APITokenSchema(Schema):
    token: str


@auth_api_router.get('/session/', response=APITokenSchema, auth=None,
                     summary="Get session API token")
def session_token(request):
    session_id = request.COOKIES.get(settings.SESSION_COOKIE_NAME, None)
    return {"token": "anonymous" if session_id is None else f"session:{session_id}"}
