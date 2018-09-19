from functools import wraps

from django.core.exceptions import PermissionDenied
from django.http import HttpResponseNotModified, HttpResponseRedirect
from django.shortcuts import render
from django.utils.cache import patch_vary_headers
from django.utils.translation import get_language

from c3nav.editor.models import ChangeSet
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.utils.user import can_access_editor


def sidebar_view(func=None, select_related=None):
    if func is None:
        def wrapped(inner_func):
            return sidebar_view(inner_func, select_related)
        return wrapped

    @wraps(func)
    def with_ajax_check(request, *args, **kwargs):
        if not can_access_editor(request):
            raise PermissionDenied

        request.changeset = ChangeSet.get_for_request(request, select_related)

        ajax = request.is_ajax() or 'ajax' in request.GET

        if not ajax:
            request.META.pop('HTTP_IF_NONE_MATCH', None)

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

    return with_ajax_check


def etag_func(request, *args, **kwargs):
    try:
        changeset = request.changeset
    except AttributeError:
        changeset = ChangeSet.get_for_request(request)
        request.changeset = changeset

    return (get_language() + ':' + changeset.raw_cache_key_by_changes + ':' +
            AccessPermission.cache_key_for_request(request, with_update=False) + ':' + str(request.user.pk or 0))
