import string
import uuid
from urllib.parse import urlencode, urljoin

import requests
from django.core.exceptions import SuspiciousOperation
from django.utils.crypto import get_random_string

from c3nav.editor.hosters.base import Hoster
from c3nav.mapdata.models.package import Package


class GitlabHoster(Hoster):
    title = 'Gitlab'

    def __init__(self, app_id, app_secret, **kwargs):
        super().__init__(**kwargs)
        self._app_id = app_id
        self._app_secret = app_secret

    def get_endpoint(self, path):
        return urljoin(self.base_url, path)

    def get_auth_uri(self, request):
        oauth_csrf_token = get_random_string(42, string.ascii_letters+string.digits)
        self._get_session_data(request)['oauth_csrf_token'] = oauth_csrf_token

        callback_uri = self._get_callback_uri(request)
        self._get_session_data(request)['callback_uri'] = callback_uri

        return self.get_endpoint('/oauth/authorize?%s' % urlencode((
            ('client_id', self._app_id),
            ('redirect_uri', callback_uri),
            ('response_type', 'code'),
            ('state', oauth_csrf_token),
        )))

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
        response = requests.post(self.get_endpoint('/oauth/token'), data={
            'client_id': self._app_id,
            'client_secret': self._app_secret,
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': callback_uri,
            'state': state,
        }).json()

        if 'error' in response:
            return {
                'state': 'logged_out',
                'error': '%s: %s' % (response['error'], response['error_description'])
            }

        return {
            'state': 'logged_in',
            'access_token': response['access_token']
        }

    def do_check_access_token(self, access_token):
        response = requests.get(self.get_endpoint('/user'), headers={'Authorization': 'Bearer '+access_token})
        if response.status_code != 200:
            return {'state': 'logged_out'}

        return {'state': 'logged_in'}

    def do_submit_edit(self, access_token, data):
        # Get endpoint URL with access token
        def endpoint_url(endpoint):
            return self.base_url + 'api/v3' + endpoint + '?access_token=' + access_token

        # Get Package from db
        try:
            package = Package.objects.get(name=data['package_name'])
        except Package.DoesNotExist:
            return self._submit_error('Could not find package.')

        # Get project name on this host, e.g. c3nav/c3nav
        project_name = '/'.join(package.home_repo[len(self.base_url):].split('/')[:2])

        # Get project from Gitlab API
        response = requests.get(endpoint_url('/projects/' + project_name.replace('/', '%2F')))
        if response.status_code != 200:
            return self._submit_error('Could not find project.')
        project = response.json()

        # Create branch
        branch_name = 'editor-%s' % uuid.uuid4()
        response = requests.post(endpoint_url('/projects/%d/repository/branches' % project['id']),
                                 data={'branch_name': branch_name, 'ref': data['commit_id']})
        if response.status_code != 201:
            return self._submit_error('Could not create branch.')

        # Make commit
        if data['action'] == 'create':
            response = requests.post(endpoint_url('/projects/%d/repository/files' % project['id']),
                                     data={'branch_name': branch_name, 'encoding': 'text', 'content': data['content'],
                                           'file_path': data['file_path'], 'commit_message': data['commit_msg']})
            if response.status_code != 201:
                return self._submit_error('Could not create file.')

        elif data['action'] == 'edit':
            response = requests.put(endpoint_url('/projects/%d/repository/files' % project['id']),
                                    data={'branch_name': branch_name, 'encoding': 'text', 'content': data['content'],
                                          'file_path': data['file_path'], 'commit_message': data['commit_msg']})
            if response.status_code != 200:
                return self._submit_error('Could not update file.')

        elif data['action'] == 'delete':
            response = requests.delete(endpoint_url('/projects/%d/repository/files' % project['id']),
                                       data={'branch_name': branch_name, 'file_path': data['file_path'],
                                             'commit_message': data['commit_msg']})
            if response.status_code != 200:
                return self._submit_error('Could not delete file.' + response.text)

        # Create merge request
        response = requests.post(endpoint_url('/projects/%d/merge_requests' % project['id']),
                                 data={'source_branch': branch_name, 'target_branch': 'master',
                                       'title': data['commit_msg']})
        if response.status_code != 201:
            return self._submit_error('Could not create merge request.')
        merge_request = response.json()

        return {
            'success': True,
            'url': merge_request['web_url']
        }

    def get_user_id_with_access_token(self, access_token):
        if not access_token.strip():
            return None

        response = requests.get(self.base_url + 'api/v3/user?private_token=' + access_token)
        if response.status_code != 200:
            return None
        return self.base_url+'user/'+str(response.json()['id'])
