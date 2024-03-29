import os
from contextlib import suppress

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import OriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "c3nav.settings")
os.environ.setdefault("C3NAV_CONN_MAX_AGE", "0")
django_asgi = get_asgi_application()

from c3nav.control.middleware import UserPermissionsChannelMiddleware  # noqa
from c3nav.urls import websocket_urlpatterns  # noqa

from c3nav import settings


class OriginValidatorWithAllowNone(OriginValidator):
    def valid_origin(self, parsed_origin):
        """
        Checks parsed origin is None.
        We want to allow None because browsers always send the Origin header and non-browser clients do not need CORS

        Pass control to the validate_origin function.

        Returns ``True`` if validation function was successful, ``False`` otherwise.
        """
        # None is not allowed unless all hosts are allowed
        if parsed_origin is None:
            return True
        return self.validate_origin(parsed_origin)


def AllowedHostsOriginValidatorWithAllowNone(app):
    """
       Factory function which returns an OriginValidatorWithAllowNone configured to use
       settings.ALLOWED_HOSTS.
       """
    allowed_hosts = settings.ALLOWED_HOSTS
    if settings.DEBUG and not allowed_hosts:
        allowed_hosts = ["localhost", "127.0.0.1", "[::1]"]
    return OriginValidatorWithAllowNone(app, allowed_hosts)


application = ProtocolTypeRouter({
    "http": django_asgi,
    "websocket": AllowedHostsOriginValidatorWithAllowNone(
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
