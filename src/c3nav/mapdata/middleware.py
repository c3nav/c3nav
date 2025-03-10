import re
from functools import wraps

from c3nav.mapdata.permissions import active_map_permissions, MapPermissionsFromRequest
from c3nav.mapdata.utils.cache.local import per_request_cache, LocalCacheProxy
from c3nav.mapdata.utils.user import get_user_data_lazy


class NoLanguageMiddleware:
    """
    Middleware that allows unsetting the Language HTTP header usind the @no_language decorator.
    """
    # todo: move this outside of mapdata tbh?
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if not getattr(response, 'no_language', False):
            return response

        if not getattr(response, 'keep_content_language', False):
            del response['Content-Language']

        if not response.has_header('Vary'):
            return response

        vary = tuple(s for s in re.split(r'\s*,\s*', response['Vary']) if s.lower() != 'accept-language')

        if vary:
            response['Vary'] = ', '.join(vary)
        else:
            del response['Vary']

        return response


def no_language(keep_content_language=False):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            response = func(*args, **kwargs)
            response.no_language = True
            response.keep_content_language = keep_content_language
            return response
        return wrapper
    return decorator


class UserDataMiddleware:
    """
    Enables getting user_data using request.user_data.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.user_data = get_user_data_lazy(request)
        return self.get_response(request)


class RequestCacheMiddleware:
    """
    Resets the request_cache at the start of every request.
    """
    # todo: move this outside of mapdata tbh?
    # todo: y'know we should really use this more
    def __init__(self, get_response):
        self.get_response = get_response
        LocalCacheProxy.enable_globally()

    def __call__(self, request):
        per_request_cache.clear()
        return self.get_response(request)


class MapPermissionsMiddleware:
    """
    Set the MapPermissions context based on the request
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with active_map_permissions.override(MapPermissionsFromRequest(request)):
            return self.get_response(request)