from functools import wraps

from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from c3nav.editor.models import ChangeSet


def sidebar_view(func=None, select_related=None):
    if func is None:
        def wrapped(inner_func):
            return sidebar_view(inner_func, select_related)
        return wrapped

    @wraps(func)
    def with_ajax_check(request, *args, **kwargs):
        request.changeset = ChangeSet.get_for_request(request, select_related)

        response = func(request, *args, **kwargs)
        if request.is_ajax() or 'ajax' in request.GET:
            if isinstance(response, HttpResponseRedirect):
                return render(request, 'editor/redirect.html', {'target': response['location']})
            response.write(render(request, 'editor/fragment_nav.html', {}).content)
            return response
        if isinstance(response, HttpResponseRedirect):
            return response
        return render(request, 'editor/map.html', {'content': response.content})
    return never_cache(with_ajax_check)
