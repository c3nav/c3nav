from django.utils.functional import SimpleLazyObject

from c3nav.control.models import UserPermissions


class UserPermissionsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.user_permissions = SimpleLazyObject(lambda: UserPermissions.get_for_user(request.user))
        return self.get_response(request)
