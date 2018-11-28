import json

from rest_framework.exceptions import ParseError


def get_api_post_data(request):
    is_json = request.META.get('CONTENT_TYPE').lower() == 'application/json'
    if is_json:
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            raise ParseError('Invalid JSON.')
        else:
            request.json_body = data
        return data
    return request.POST
