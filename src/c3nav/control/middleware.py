from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware as BaseChannelsMiddleware
from django.utils.functional import LazyObject, SimpleLazyObject, lazy

from c3nav.control.models import UserPermissions, UserSpaceAccess


class UserPermissionsLazyObject(LazyObject):
    def _setup(self):
        raise ValueError("Accessing scope user before it is ready.")


class UserPermissionsMiddleware:
    """
    This middleware adds request.user_permissions to get the UserPermissions for the current request/user.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def get_user_permissions(self, request):
        try:
            return getattr(request, '_user_permissions_cache')
        except AttributeError:
            pass
        result = UserPermissions.get_for_user(request.user)
        self._user_permissions_cache = result
        return result

    def get_user_space_accesses(self, request):
        try:
            return getattr(request, '_user_space_accesses_cache')
        except AttributeError:
            pass
        result = UserSpaceAccess.get_for_user(request.user)
        self._user_space_accesses_cache = result
        return result

    def __call__(self, request):
        request.user_permissions = SimpleLazyObject(lambda: self.get_user_permissions(request))
        request.user_space_accesses = lazy(self.get_user_space_accesses, dict)(request)
        return self.get_response(request)


class UserPermissionsChannelMiddleware(BaseChannelsMiddleware):
    async def __call__(self, scope, receive, send):
        # todo: this doesn't seem to actually be lazy. and scope["user"] isn't either?
        scope["user_permissions"] = UserPermissionsLazyObject()
        scope["user_permissions"]._wrapped = await database_sync_to_async(UserPermissions.get_for_user)(scope["user"])

        return await super().__call__(scope, receive, send)
