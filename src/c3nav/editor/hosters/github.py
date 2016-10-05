import base64
import string
import time
import uuid
from urllib.parse import urlencode

import requests
from django.core.exceptions import SuspiciousOperation
from django.utils.crypto import get_random_string

from c3nav.editor.hosters.base import Hoster
from c3nav.mapdata.models.package import Package


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
            return {
                'state': 'logged_out',
                'error': '%s: %s %s' % (response['error'], response['error_description'], response['error_uri'])
            }

        if 'public_repo' not in response['scope'].split(','):
            return {
                'state': 'missing_permissions',
                'access_token': response['access_token']
            }

        return {
            'state': 'logged_in',
            'access_token': response['access_token']
        }

    def do_check_access_token(self, access_token):
        response = requests.get('https://api.github.com/rate_limit', headers={'Authorization': 'token '+access_token})
        if response.status_code != 200:
            return {'state': 'logged_out'}

        if 'public_repo' not in (s.strip() for s in response.headers.get('X-OAuth-Scopes').split(',')):
            return {'state': 'missing_permissions'}

        return {'state': 'logged_in'}

    def do_submit_edit(self, access_token, data):
        # Get endpoint URL with access token
        def endpoint_url(endpoint):
            return 'https://api.github.com/' + endpoint[1:] + '?access_token=' + access_token

        # Check access token
        state = self.do_check_access_token(access_token)['state']
        if state == 'logged_out':
            return self._submit_error('The access token is no longer working. Please sign in again.')
        if state == 'missing_permissions':
            return self._submit_error('Missing Permissions. Please sign in again.')

        # Get Package from db
        try:
            package = Package.objects.get(name=data['package_name'])
        except Package.DoesNotExist:
            return self._submit_error('Could not find package.')

        # Get repo name on this host, e.g. c3nav/c3nav
        repo_name = '/'.join(package.home_repo[len(self.base_url):].split('/')[:2])

        # todo: form

        # Get user
        response = requests.get(endpoint_url('/user'))
        if response.status_code != 200:
            return self._submit_error('Could not get user.')
        user = response.json()

        # Check if there is already a fork. If not, create one.
        fork_name = user['login'] + '/' + repo_name.split('/')[1]
        fork_created = False
        for i in range(10):
            response = requests.get(endpoint_url('/repos/%s' % fork_name), allow_redirects=False)
            if response.status_code == 200:
                # Something that could be a fork exists, check if it is one
                fork = response.json()
                if fork['fork'] and fork['parent']['full_name'] == repo_name:
                    # It's a fork and it's the right one!
                    break
                else:
                    return self._submit_error('Could not create fork: there already is a repo with the same name.')

            elif response.status_code in (404, 301):
                if not fork_created:
                    # Fork does not exist, create it
                    # Creating forks happens asynchroniously, so we will stay in the loop to check repeatedly if the
                    # fork does exist until we run into a timeout.
                    response = requests.post(endpoint_url('/repos/%s/forks' % repo_name))
                    fork_created = True
                else:
                    # Fork was not created yet. Wait a moment, then try again.
                    time.sleep(4)
            else:
                return self._submit_error('Could not check for existing fork: error %d' % response.status_code)

        else:
            # We checked multiple timeas and waited more than half a minute. Enough is enorugh.
            return self._submit_error('Could not create fork: fork creation timeout.')

        # Create branch
        branch_name = 'editor-%s' % uuid.uuid4()
        response = requests.post(endpoint_url('/repos/%s/git/refs' % fork_name),
                                 json={'ref': 'refs/heads/'+branch_name, 'sha': data['commit_id']})
        if response.status_code != 201:
            return self._submit_error('Could not create branch.')

        # Make commit
        if data['action'] == 'create':
            response = requests.put(endpoint_url('/repos/%s/contents/%s' % (fork_name, data['file_path'])),
                                    json={'branch': branch_name, 'message': data['commit_msg'],
                                          'content': base64.b64encode(data['content'].encode()).decode()})
            if response.status_code != 201:
                return self._submit_error('Could not create file.'+response.text)

        else:
            response = requests.get(endpoint_url('/repos/%s/contents/%s' % (fork_name, data['file_path'])),
                                    params={'ref': data['commit_id']})
            if response.status_code != 200:
                return self._submit_error('Could not get file.')
            file_sha = response.json()['sha']

            if data['action'] == 'edit':
                response = requests.put(endpoint_url('/repos/%s/contents/%s' % (fork_name, data['file_path'])),
                                        json={'branch': branch_name, 'message': data['commit_msg'], 'sha': file_sha,
                                              'content': base64.b64encode(data['content'].encode()).decode()})
                if response.status_code != 200:
                    return self._submit_error('Could not update file.')

            elif data['action'] == 'delete':
                response = requests.put(endpoint_url('/repos/%s/contents/%s' % (fork_name, data['file_path'])),
                                        json={'branch': branch_name, 'message': data['commit_msg'], 'sha': file_sha})
                if response.status_code != 200:
                    return self._submit_error('Could not delete file.' + response.text)

        # Create pull request
        response = requests.post(endpoint_url('/repos/%s/pulls' % repo_name),
                                 json={'base': 'master', 'head': '%s:%s' % (user['login'], branch_name),
                                       'title': data['commit_msg']})
        if response.status_code != 201:
            return self._submit_error('Could not delete file.' + response.text)
        merge_request = response.json()

        return {
            'success': True,
            'url': merge_request['html_url']
        }
