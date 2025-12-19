from functools import wraps


def allow_cors():
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            response = func(request, *args, **kwargs)
            origin_header = request.META.get("HTTP_ORIGIN", "null")
            if origin_header != "null":
                response["Access-Control-Allow-Origin"] = origin_header
                if "ETag" in response:
                    response['Access-Control-Expose-Headers'] = 'ETag'
            return response
        return wrapper
    return decorator