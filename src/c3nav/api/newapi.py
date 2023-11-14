from django.conf import settings
from ninja import Router as APIRouter
from ninja import Schema

auth_api_router = APIRouter(tags=["auth"])


class APITokenSchema(Schema):
    token: str


@auth_api_router.get('/session/', response=APITokenSchema,
                     summary="Get session API token")
def session_token(request):
    print()
    return {"token": request.COOKIES.get(settings.SESSION_COOKIE_NAME, 'anonymous')}
