import re
from functools import wraps


class NoLanguageMiddleware:
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
