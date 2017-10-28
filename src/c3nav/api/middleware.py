class RemoveEtagFromHTMLApiViewMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if request.path.startswith('/api/'):
            if response['content-type'].startswith('text/html') and response.has_header('etag'):
                del response['etag']

        return response
