class MobileclientMiddleware:
    """
    This middleware adds request.mobileclient
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.mobileclient = 'c3navclient' in request.META['HTTP_USER_AGENT']
        return self.get_response(request)
