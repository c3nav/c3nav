from abc import ABC, abstractmethod

from django.urls.base import reverse

from c3nav.editor.tasks import check_access_token, request_access_token
from c3nav.mapdata.models import Package


class Hoster(ABC):
    def __init__(self, name, base_url):
        self.name = name
        self.base_url = base_url

    def get_packages(self):
        """
        Get a Queryset of all packages that can be handled by this hoster
        """
        return Package.objects.filter(home_repo__startswith=self.base_url)

    def _get_callback_uri(self, request):
        return request.build_absolute_uri(reverse('editor.finalize.oauth.callback', kwargs={'hoster': self.name}))

    def _get_session_data(self, request):
        request.session.modified = True
        return request.session.setdefault('hosters', {}).setdefault(self.name, {})

    def get_error(self, request):
        """
        If an error occured lately, return and forget it.
        """
        session_data = self._get_session_data(request)
        if 'error' in session_data:
            return session_data.pop('error')

    def set_tmp_data(self, request, data):
        """
        Save data before redirecting to the OAuth Provider.
        """
        self._get_session_data(request)['tmp_data'] = data

    def get_tmp_data(self, request):
        """
        Get and forget data that was saved before redirecting to the OAuth Provider.
        """
        data = self._get_session_data(request)
        if 'tmp_data' not in data:
            return None
        return data.pop('tmp_data')

    def get_state(self, request):
        """
        Get current hoster state for this user.
        :return: 'logged_in', 'logged_out', 'missing_permissions' or 'checking' if a check is currently running.
        """
        session_data = self._get_session_data(request)
        state = session_data.setdefault('state', 'logged_out')

        if state == 'checking':
            task = request_access_token.AsyncResult(id=session_data.get('checking_progress_id'))
            self._handle_checking_task(request, task, session_data)
            state = session_data['state']

        return state

    def check_state(self, request):
        """
        Sets the state for this user to 'checking' immediately and starts a task that checks if the currently known
        is still valid and sets the state afterwards.

        Does nothing if the current state is not 'logged_in'.
        """
        session_data = self._get_session_data(request)
        state = session_data.get('state')

        if state == 'logged_in':
            session_data['state'] = 'checking'
            task = check_access_token.delay(hoster=self.name, access_token=session_data['access_token'])
            session_data['checking_progress_id'] = task.id
            self._handle_checking_task(request, task, session_data)

    def _handle_checking_task(self, request, task, session_data):
        """
        Checks if the checking task is finished and if so handles its results.
        """
        if task.ready():
            task.maybe_reraise()
            state, content = task.result
            if content:
                if state == 'logged_out':
                    session_data['error'] = content
                else:
                    session_data['access_token'] = content
            session_data['state'] = state
            session_data.pop('checking_progress_id')

    def request_access_token(self, request, *args, **kwargs):
        """
        Starts a task that calls do_request_access_token.
        """
        args = (self.name, )+args
        session_data = self._get_session_data(request)
        session_data['state'] = 'checking'
        task = request_access_token.apply_async(args=args, kwargs=kwargs)
        session_data['checking_progress_id'] = task.id
        self._handle_checking_task(request, task, session_data)

    @abstractmethod
    def get_auth_uri(self, request):
        """
        Get the a URL the user should be redirected to to authenticate and invalidates any previous URLs.
        """
        pass

    @abstractmethod
    def handle_callback_request(self, request):
        """
        Validates and handles the callback request and calls request_access_token.
        """
        pass

    @abstractmethod
    def do_request_access_token(self, code, state):
        """
        Task method for requesting the access token asynchroniously.
        Return a tuple with a new state and the access_token, or an optional error string if the state is 'logged_out'.
        """
        pass

    @abstractmethod
    def do_check_access_token(self, access_token):
        """
        Task method for checking the access token asynchroniously.
        Return a tuple with a new state and None, or an optional error string if the state is 'logged_out'.
        """
        pass
