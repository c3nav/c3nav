from rest_framework.authentication import SessionAuthentication


class ForceCSRFCheckSessionAuthentication(SessionAuthentication):

    def authenticate(self, request):
        result = super().authenticate(request)

        if result is None:
            self.enforce_csrf(request)

        return result
