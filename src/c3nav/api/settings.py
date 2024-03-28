from django.core.handlers.wsgi import WSGIRequest
from ninja import Router as APIRouter

settings_api_router = APIRouter(tags=["settings"])


@settings_api_router.post('/theme/', auth=None, summary="set the theme for the current session")
def session_key(request: WSGIRequest, id: str | int):
    if request.session.session_key is None:
        request.session.create()

    request.session['theme'] = int(id)

    return (200,)
