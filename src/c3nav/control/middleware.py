from django.utils.functional import SimpleLazyObject

from c3nav.control.models import UserPermissions


class UserPermissionsMiddleware:
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

    def __call__(self, request):
        request.user_permissions = SimpleLazyObject(lambda: self.get_user_permissions(request))
        return self.get_response(request)
