import string
from urllib.parse import urlencode

import requests
from django.core.exceptions import SuspiciousOperation
from django.utils.crypto import get_random_string

from c3nav.editor.hosters.base import Hoster


class GithubHoster(Hoster):
    title = 'GitHub'

    def __init__(self, app_id, app_secret, **kwargs):
        super().__init__(**kwargs)
        self._app_id = app_id
        self._app_secret = app_secret

    def get_auth_uri(self, request):
        oauth_csrf_token = get_random_string(42, string.ascii_letters+string.digits)
        self._get_session_data(request)['oauth_csrf_token'] = oauth_csrf_token

        callback_uri = self._get_callback_uri(request).replace('://localhost:8000', 's://33c3.c3nav.de')
        self._get_session_data(request)['callback_uri'] = callback_uri

        return 'https://github.com/login/oauth/authorize?%s' % urlencode((
            ('client_id', self._app_id),
            ('redirect_uri', callback_uri),
            ('scope', 'public_repo'),
            ('state', oauth_csrf_token),
        ))

    def handle_callback_request(self, request):
        code = request.GET.get('code')
        state = request.GET.get('state')
        if code is None or state is None:
            raise SuspiciousOperation('Missing parameters.')

        session_data = self._get_session_data(request)
        if session_data.get('oauth_csrf_token') != state:
            raise SuspiciousOperation('OAuth CSRF token mismatch')
        session_data.pop('oauth_csrf_token')

        callback_uri = session_data.pop('callback_uri')

        self.request_access_token(request, code, state, callback_uri)

    def do_request_access_token(self, code, state, callback_uri):
        response = requests.post('https://github.com/login/oauth/access_token', data={
            'client_id': self._app_id,
            'client_secret': self._app_secret,
            'code': code,
            'redirect_uri': callback_uri,
            'state': state
        }, headers={'Accept': 'application/json'}).json()

        if 'error' in response:
            return ('logged_out',
                    '%s: %s %s' % (response['error'], response['error_description'], response['error_uri']))

        if 'public_repo' not in response['scope'].split(','):
            return ('missing_permissions', response['access_token'])

        return ('logged_in', response['access_token'])

    def do_check_access_token(self, access_token):
        response = requests.get('https://api.github.com/rate_limit', headers={'Authorization': 'token '+access_token})
        if response.status_code != 200:
            return ('logged_out', '')

        if 'public_repo' not in (s.strip() for s in response.headers.get('X-OAuth-Scopes').split(',')):
            return ('missing_permissions', None)

        return ('logged_in', None)
