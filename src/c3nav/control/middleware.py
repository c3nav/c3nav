from django.utils.functional import SimpleLazyObject, lazy

from c3nav.control.models import UserPermissions, UserSpaceAccess


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
