from rest_framework.exceptions import ParseError


def get_api_post_data(request):
    is_json = request.META.get('CONTENT_TYPE').lower() == 'application/json'
    if is_json:
        try:
            data = request.json_body
        except AttributeError:
            raise ParseError('Invalid JSON.')
        return data
    return request.POST
