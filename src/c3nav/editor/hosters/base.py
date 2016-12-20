from abc import ABC, abstractmethod
from urllib.parse import urlparse, urlunparse

from celery.result import AsyncResult
from django.conf import settings
from django.urls.base import reverse
from django.utils.translation import ugettext_lazy as _

from c3nav.editor.tasks import check_access_token_task, request_access_token_task, submit_edit_task
from c3nav.mapdata.models import Package


class Hoster(ABC):
    def __init__(self, name, base_url):
        self.name = name
        self.base_url = base_url

    def get_packages(self):
        """
        Get a Queryset of all packages that can be handled by this hoster
        """
        return Package.objects.filter(home_repo__startswith=self.base_url).order_by('name')

    def _get_callback_uri(self, request):
        uri = request.build_absolute_uri(reverse('editor.oauth.callback', kwargs={'hoster': self.name}))
        if settings.OAUTH_CALLBACK_SCHEME is None and settings.OAUTH_CALLBACK_NETLOC is None:
            return uri

        parts = list(urlparse(uri))
        if settings.OAUTH_CALLBACK_SCHEME is not None:
            parts[0] = settings.OAUTH_CALLBACK_SCHEME
        if settings.OAUTH_CALLBACK_NETLOC is not None:
            parts[1] = settings.OAUTH_CALLBACK_NETLOC
        return urlunparse(parts)

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

    def get_state(self, request):
        """
        Get current hoster state for this user.
        :return: 'logged_in', 'logged_out', 'missing_permissions' or 'checking' if a check is currently running.
        """
        session_data = self._get_session_data(request)
        state = session_data.setdefault('state', 'logged_out')

        if state == 'checking':
            task = AsyncResult(id=session_data.get('checking_progress_id'))
            if settings.CELERY_ALWAYS_EAGER:
                task.maybe_reraise()
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
            task = check_access_token_task.delay(hoster=self.name, access_token=session_data['access_token'])
            if settings.CELERY_ALWAYS_EAGER:
                task.maybe_reraise()
            session_data['checking_progress_id'] = task.id
            self._handle_checking_task(request, task, session_data)

    def _handle_checking_task(self, request, task, session_data):
        """
        Checks if the checking task is finished and if so handles its results.
        """
        if task.ready():
            if task.failed():
                session_data['state'] = 'logged_out'
                session_data['error'] = _('Internal error.')
            else:
                result = task.result
                session_data.update(result)  # updates 'state' key and optional 'error' and 'access_tokenÄ keys.
            session_data.pop('checking_progress_id')

    def request_access_token(self, request, *args, **kwargs):
        """
        Starts a task that calls do_request_access_token.
        """
        args = (self.name, )+args
        session_data = self._get_session_data(request)
        session_data['state'] = 'checking'
        task = request_access_token_task.apply_async(args=args, kwargs=kwargs)
        session_data['checking_progress_id'] = task.id
        self._handle_checking_task(request, task, session_data)

    def submit_edit(self, request, data):
        session_data = self._get_session_data(request)
        task = submit_edit_task.delay(hoster=self.name, access_token=session_data['access_token'], data=data)
        if settings.CELERY_ALWAYS_EAGER:
            task.maybe_reraise()
        return task

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
    def do_request_access_token(self, *args, **kwargs):
        """
        Task method for requesting the access token asynchroniously.
        Returns a dict with a 'state' key containing the new hoster state, an optional 'error' key containing an
        error message and an optional 'access_token' key containing a new access token.
        """
        pass

    @abstractmethod
    def do_check_access_token(self, access_token):
        """
        Task method for checking the access token asynchroniously.
        Returns a dict with a 'state' key containing the new hoster state.
        """
        pass

    def _submit_error(self, error):
        return {
            'success': False,
            'error': error
        }

    @abstractmethod
    def do_submit_edit(self, access_token, data):
        """
        Task method for submitting an edit (e.g. creating a pull request).

        Returns a dict with a 'success' key that contains a boolean, an optional 'error' key containing an error
        message and an optional 'url' key containing an URL to the created pull request.
        """
        pass

    @abstractmethod
    def get_user_id_with_access_token(self, access_token) -> str:
        """
        Get User ID of the User with this access token or None if the access token does not work.
        """
        pass
