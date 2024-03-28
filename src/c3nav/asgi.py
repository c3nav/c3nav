import os
from contextlib import suppress

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "c3nav.settings")
os.environ.setdefault("C3NAV_CONN_MAX_AGE", "0")
django_asgi = get_asgi_application()

from c3nav.control.middleware import UserPermissionsChannelMiddleware  # noqa
from c3nav.urls import websocket_urlpatterns  # noqa

application = ProtocolTypeRouter({
    "http": django_asgi,
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            UserPermissionsChannelMiddleware(
                URLRouter(websocket_urlpatterns),
            ),
        ),
    ),
})

# optional support for static files via starlette
with suppress(ImportError):
    # settings need to be loaded after django init via get_asgi_application
    from django.conf import settings
    from starlette.applications import Starlette
    from starlette.routing import Mount
    from starlette.staticfiles import StaticFiles

    static_app = ProtocolTypeRouter({
        "http": Starlette(routes=[
            Mount(
                path=settings.STATIC_URL,
                app=StaticFiles(directory=settings.STATIC_ROOT, follow_symlink=True),
                name='static',
            ),
            Mount(path='/', app=django_asgi),
        ]),
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(
                UserPermissionsChannelMiddleware(
                    URLRouter(websocket_urlpatterns),
                ),
            ),
        ),
    })
