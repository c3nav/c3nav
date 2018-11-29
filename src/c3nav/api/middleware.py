import json


class JsonRequestBodyMiddleware:
    """
    Enables posting JSON requests.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        is_json = request.META.get('CONTENT_TYPE').lower() == 'application/json'
        if is_json:
            try:
                request.json_body = json.loads(request.body)
            except json.JSONDecodeError:
                pass
        return self.get_response(request)
