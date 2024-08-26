from abc import ABC, abstractmethod
from collections import OrderedDict
from functools import wraps
from typing import Optional

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.contrib.messages import DEFAULT_TAGS as DEFAULT_MESSAGE_TAGS
from django.contrib.messages import get_messages
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.http import HttpResponse, HttpResponseNotModified, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.utils.cache import patch_vary_headers
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from c3nav.editor.models import ChangeSet
from c3nav.editor.overlay import DatabaseOverlayManager
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.models.base import SerializableMixin
from c3nav.mapdata.utils.user import can_access_editor


def accesses_mapdata(func):
    @wraps(func)
    def wrapped(request, *args, **kwargs):
        changes = None if request.changeset.direct_editing is None else request.changeset.changes
        with DatabaseOverlayManager.enable(changes, commit=request.changeset.direct_editing) as manager:
            result = func(request, *args, **kwargs)
            print("operations", manager.new_operations)
            return result

    return wrapped


def sidebar_view(func=None, select_related=None, api_hybrid=False):
    if func is None:
        def wrapped(inner_func):
            return sidebar_view(inner_func, select_related=select_related, api_hybrid=api_hybrid)
        return wrapped

    @wraps(func)
    def wrapped(request, *args, api=False, **kwargs):
        if api and not api_hybrid:
            raise Exception('API call on a view without api_hybrid!')

        if not can_access_editor(request):
            raise PermissionDenied

        request.changeset = ChangeSet.get_for_request(request, select_related)

        if api:
            request.is_delete = request.method == 'DELETE'
            return call_api_hybrid_view_for_api(func, request, *args, **kwargs)

        ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'ajax' in request.GET
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
                if request.mobileclient:
                    response.write(render(request, 'editor/fragment_mobileclientdata.html', {}).content)
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

    def add_headers(self, response):
        if self.etag is not None:
            response['ETag'] = self.etag
        if self.last_modified is not None:
            response['Last-Modified'] = self.last_modified
        return response

    @abstractmethod
    def get_api_response(self, request):
        pass

    @abstractmethod
    def get_html_response(self, request):
        pass


class APIHybridMessageRedirectResponse(APIHybridResponse):
    def __init__(self, level, message, redirect_to, status_code=None):
        self.level = level
        self.message = message
        self.redirect_to = redirect_to
        if self.level == 'error' and status_code is None:
            raise Exception('Error with HTTP 200 makes no sense!')
        self.status_code = status_code

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
    name_to_type_mapping = {
        'geometry': 'geojson'
    }
    type_mapping = {
        'TextInput': 'text',
        'NumberInput': 'number',
        'Textarea': 'text',
        'CheckboxInput': 'boolean',
        'Select': 'single_choice',
        'SelectMultiple': 'multiple_choice',
        'HiddenInput': 'hidden',
    }
    type_required_mapping = {
        # name, inverted, only_required
        'TextInput': ('allowed_empty', True, False),
        'NumberInput': ('null_allowed', True, False),
        'Textarea': ('allowed_empty', True, False),
        'CheckboxInput': ('true_required', False, True),
        'Select': ('choice_required', False, False),
        'SelectMultiple': ('choice_required', False, False),
        'HiddenInput': ('null_allowed', True, False),
    }

    def __init__(self, template: str, ctx: dict, form, error: Optional[APIHybridError]):
        self.template = template
        self.ctx = ctx
        self.form = form
        self.error = error

    def get_api_response(self, request):
        result = {}
        if self.error:
            result['error'] = self.error.message
            self.status_code = self.error.status_code
        if request.method == 'POST':
            if not self.form.is_valid():
                if self.status_code is None:
                    self.status_code = 400
                result['form_errors'] = self.form.errors
        else:
            form = OrderedDict()
            for name, field in self.form.fields.items():
                widget = field.widget
                required = field.required
                field = {
                    'type': self.name_to_type_mapping.get(name, None) or self.type_mapping[type(widget).__name__],
                }
                required_name, required_invert, required_only_true = self.type_required_mapping[type(widget).__name__]
                if not required_only_true or required:
                    field[required_name] = not required if required_invert else required
                if hasattr(widget, 'choices'):
                    field['choices'] = dict(widget.choices)
                if hasattr(widget, 'disabled'):
                    field['disabled'] = True
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
        response = render(request, self.template, self.ctx)
        return self.add_headers(response) if request.method == 'GET' else response


class APIHybridTemplateContextResponse(APIHybridResponse):
    def __init__(self, template: str, ctx: dict, fields=None):
        self.template = template
        self.ctx = ctx
        self.fields = fields

    def _maybe_serialize_value(self, value):
        if isinstance(value, SerializableMixin):
            value = value.serialize(geometry=False, detailed=False)
        elif isinstance(value, QuerySet) and issubclass(value.model, SerializableMixin):
            value = [item.serialize(geometry=False, detailed=False) for item in value]
        return value

    def get_api_response(self, request):
        result = self.ctx
        if self.fields:
            result = {name: self._maybe_serialize_value(value)
                      for name, value in result.items() if name in self.fields}
        return result

    def get_html_response(self, request):
        response = render(request, self.template, self.ctx)
        return self.add_headers(response) if request.method == 'GET' else response


class NoAPIHybridResponse(Exception):
    pass


def call_api_hybrid_view_for_api(func, request, *args, **kwargs):
    response = func(request, *args, **kwargs)
    if isinstance(response, APIHybridResponse):
        result = OrderedDict(response.get_api_response(request))

        messages = []
        for message in get_messages(request):
            messages.append({
                'level': DEFAULT_MESSAGE_TAGS[message.level],
                'message': message.message
            })
        if messages:
            result['messages'] = messages
            result.move_to_end('messages', last=False)

        # todo: fix this
        # api_response = APIResponse(result, status=response.status_code)
        # if request.method == 'GET':
        #     response.add_headers(api_response)
        # return api_response
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


def editor_etag_func(request, *args, **kwargs):
    try:
        changeset = request.changeset
    except AttributeError:
        changeset = ChangeSet.get_for_request(request)
        request.changeset = changeset

    return (get_language() + ':' + changeset.raw_cache_key_by_changes + ':' +
            AccessPermission.cache_key_for_request(request, with_update=False) + ':' + str(request.user.pk or 0)
            + ':' + str(int(request.user_permissions.can_access_base_mapdata))
            + ':' + ','.join(str(i) for i in request.user_space_accesses)
            + ':' + str(int(request.user.is_superuser))
            + ':' + str(int(request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'ajax' in request.GET)))
