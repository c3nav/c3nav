class MobileclientMiddleware:
    """
    This middleware adds request.mobileclient
    """
    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def is_mobileclient(request):
        if 'fakemobileclient' in request.GET:
            return True

        user_agent = request.META.get('HTTP_USER_AGENT', '')
        if not user_agent.startswith('c3navClient/'):
            return False

        user_agent = user_agent[12:].split('/')
        if len(user_agent) < 2:
            return False

        app_platform, app_version = user_agent[0:2]
        if app_platform == 'Android':
            # activate new mobileclient features for the c3nav android app 4.0.0 or higher
            # yep, iphone app can't do this stuff yet
            if not app_version.isdigit():
                return False
            app_version = int(app_version)
            return app_version >= 14040000

        return False

    def __call__(self, request):
        request.mobileclient = self.is_mobileclient(request)
        return self.get_response(request)
