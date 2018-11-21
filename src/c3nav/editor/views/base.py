from abc import ABC, abstractmethod
from collections import OrderedDict
from functools import wraps
from typing import Optional

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseNotModified, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.utils.cache import patch_vary_headers
from django.utils.translation import get_language
from django.utils.translation import ugettext_lazy as _
from rest_framework.response import Response as APIResponse

from c3nav.editor.models import ChangeSet
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.utils.user import can_access_editor


def sidebar_view(func=None, select_related=None, api_hybrid=False, allow_post=True, allow_delete=True):
    if func is None:
        def wrapped(inner_func):
            return sidebar_view(inner_func, select_related=select_related, api_hybrid=api_hybrid,
                                allow_post=True, allow_delete=True)
        return wrapped

    @wraps(func)
    def wrapped(request, *args, api=False, **kwargs):
        if api and not api_hybrid:
            raise Exception('API call on a view without api_hybrid!')

        if not can_access_editor(request):
            raise PermissionDenied

        request.changeset = ChangeSet.get_for_request(request, select_related)

        if api:
            return call_api_hybrid_view_for_api(func, request, *args, **kwargs)

        ajax = request.is_ajax() or 'ajax' in request.GET
        if not ajax:
            request.META.pop('HTTP_IF_NONE_MATCH', None)

        if api_hybrid:
            response = call_api_hybrid_view_for_html(func, request, *args, **kwargs)
        else:
            response = func(request, *args, **kwargs)

        if ajax:
            if isinstance(response, HttpResponseRedirect):
                return render(request, 'editor/redirect.html', {'target': response['location']})
            if not isinstance(response, HttpResponseNotModified):
                response.write(render(request, 'editor/fragment_nav.html', {}).content)
            response['Cache-Control'] = 'no-cache'
            patch_vary_headers(response, ('X-Requested-With', ))
            return response
        if isinstance(response, HttpResponseRedirect):
            return response
        response = render(request, 'editor/map.html', {'content': response.content.decode()})
        response['Cache-Control'] = 'no-cache'
        patch_vary_headers(response, ('X-Requested-With', ))
        return response

    wrapped.api_hybrid = api_hybrid
    wrapped.allow_post = allow_post
    wrapped.allow_delete = allow_delete

    return wrapped


class APIHybridResponse(ABC):
    status_code = None
    etag = None
    last_modified = None

    def has_header(self, header):
        header = header.lower()
        if header == 'etag':
            return self.etag is not None
        elif header == 'last-modified':
            return self.last_modified is not None
        else:
            raise KeyError

    def __setitem__(self, header, value):
        header = header.lower()
        if header == 'etag':
            self.etag = value
        elif header == 'last-modified':
            self.last_modified = value
        else:
            raise KeyError

    def setdefault(self, header, value):
        if not self.has_header(header):
            self[header] = value

    @abstractmethod
    def get_api_response(self, request):
        pass

    @abstractmethod
    def get_html_response(self, request):
        pass


class APIHybridMessageRedirectResponse(APIHybridResponse):
    def __init__(self, level, message, redirect_to):
        self.level = level
        self.message = message
        self.redirect_to = self.redirect_to

    def get_api_response(self, request):
        return {self.level: self.message}

    def get_html_response(self, request):
        getattr(messages, self.level)(request, self.message)
        return redirect(self.redirect_to)


class APIHybridLoginRequiredResponse(APIHybridResponse):
    def __init__(self, next, login_url=None, level='error', message=_('Log in required.')):
        self.login_url = login_url
        self.next = next
        self.level = level
        self.message = message

    def get_api_response(self, request):
        return {self.level: self.message}

    def get_html_response(self, request):
        getattr(messages, self.level)(request, self.message)
        return redirect_to_login(self.next, self.login_url)


class APIHybridError:
    def __init__(self, status_code: int, message):
        self.status_code = status_code
        self.message = message


class APIHybridFormTemplateResponse(APIHybridResponse):
    type_mapping = {
        'TextInput': 'text',
        'NumberInput': 'number',
        'Textarea': 'text',
        'CheckboxInput': 'boolean',
        'Select': 'single_choice',
        'SelectMultiple': 'multiple_choice',
    }

    def __init__(self, template: str, ctx: dict, form, error: Optional[APIHybridError]):
        self.template = template
        self.ctx = ctx
        self.form = form
        self.error = error

    def get_api_response(self, request):
        result = {}
        if self.error:
            result['error'] = str(self.error.message)
            self.status_code = self.error.status_code
        if request.method == 'POST':
            if not self.form.is_valid():
                if not self.form.is_valid() and self.status_code is None:
                    self.status_code = 400
                result['form_errors'] = self.form.errors
        else:
            form = OrderedDict()
            for name, field in self.form.fields.items():
                widget = field.widget
                field = {
                    'type': self.type_mapping[type(widget).__name__],
                    "required": field.required
                }
                if hasattr(widget, 'choices'):
                    field['choices'] = dict(widget.choices)
                field.update(widget.attrs)
                field.update({
                    'value': self.form[name].value(),
                })
                form[name] = field
            result['form'] = form
        return result

    def get_html_response(self, request):
        if self.error:
            messages.error(request, self.error.message)
        return render(request, self.template, self.ctx)


class NoAPIHybridResponse(Exception):
    pass


def call_api_hybrid_view_for_api(func, request, *args, **kwargs):
    response = func(request, *args, **kwargs)
    if isinstance(response, APIHybridResponse):
        api_response = APIResponse(response.get_api_response(request), status=response.status_code)
        if response.etag:
            api_response['ETag'] = response.etag
        if response.last_modified:
            api_response['Last-Modified'] = response.last_modified
        return api_response
    elif isinstance(response, HttpResponse) and response.status_code in (304, 412):
        # 304 Not Modified, 412 Precondition Failed
        return response
    raise NoAPIHybridResponse


def call_api_hybrid_view_for_html(func, request, *args, **kwargs):
    response = func(request, *args, **kwargs)
    if isinstance(response, APIHybridResponse):
        return response.get_html_response(request)
    elif isinstance(response, HttpResponse) and response.status_code in (304, 412):
        # 304 Not Modified, 412 Precondition Failed
        return response
    raise NoAPIHybridResponse


def etag_func(request, *args, **kwargs):
    try:
        changeset = request.changeset
    except AttributeError:
        changeset = ChangeSet.get_for_request(request)
        request.changeset = changeset

    return (get_language() + ':' + changeset.raw_cache_key_by_changes + ':' +
            AccessPermission.cache_key_for_request(request, with_update=False) + ':' + str(request.user.pk or 0)
            + ':' + str(int(request.user_permissions.can_access_base_mapdata))
            + ':' + str(int(request.user.is_superuser)))
