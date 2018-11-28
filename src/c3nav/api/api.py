from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.middleware import csrf
from django.utils.translation import ugettext_lazy as _
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import ParseError, PermissionDenied
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from c3nav.api.models import Token
from c3nav.api.utils import get_api_post_data


class SessionViewSet(ViewSet):
    """
    Session for Login, Logout, etc…
    Don't forget to set X-Csrftoken for POST requests!

    /login – POST with fields token or username and password to log in
    /get_token – POST with fields username and password to get a login token
    /logout - POST to log out
    """
    def list(self, request, *args, **kwargs):
        return Response({
            'is_authenticated': request.user.is_authenticated,
            'csrf_token': csrf.get_token(request),
        })

    @action(detail=False, methods=['post'])
    def login(self, request, *args, **kwargs):
        # django-rest-framework doesn't do this for logged out requests
        SessionAuthentication().enforce_csrf(request)

        if request.user.is_authenticated:
            raise ParseError(_('Log out first.'))

        data = get_api_post_data(request)

        if 'token' in data:
            try:
                token = Token.get_by_token(data['token'])
            except Token.DoesNotExist:
                raise PermissionDenied(_('This token does not exist or is no longer valid.'))
            user = token.user
        elif 'username' in data:
            form = AuthenticationForm(request, data=data)
            if not form.is_valid():
                raise ParseError(form.errors)
            user = form.user_cache
        else:
            raise ParseError(_('You need to send a token or username and password.'))

        login(request, user)

        return Response({
            'detail': _('Login successful.'),
            'csrf_token': csrf.get_token(request),
        })

    @action(detail=False, methods=['post'])
    def get_token(self, request, *args, **kwargs):
        # django-rest-framework doesn't do this for logged out requests
        SessionAuthentication().enforce_csrf(request)

        data = get_api_post_data(request)

        form = AuthenticationForm(request, data=data)
        if not form.is_valid():
            raise ParseError(form.errors)

        token = form.user_cache.login_tokens.create()

        return Response({
            'token': token.get_token(),
        })

    @action(detail=False, methods=['post'])
    def logout(self, request, *args, **kwargs):
        # django-rest-framework doesn't do this for logged out requests
        SessionAuthentication().enforce_csrf(request)

        if not request.user.is_authenticated:
            return ParseError(_('Not logged in.'))

        logout(request)

        return Response({
            'detail': _('Logout successful.'),
            'csrf_token': csrf.get_token(request),
        })
