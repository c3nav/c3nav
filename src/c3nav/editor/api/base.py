from functools import wraps

from c3nav.editor.models import ChangeSet
from c3nav.editor.views.base import editor_base_etag_func
from c3nav.mapdata.api.base import api_etag


def api_etag_with_update_cache_key(permissions=True, base_etag_func=editor_base_etag_func, base_mapdata=False):
    if base_etag_func != editor_base_etag_func:
        raise TypeError('Be sure this is okay before using something else.')

    def inner_wrapper(func):
        func = api_etag(permissions=permissions, base_etag_func=base_etag_func, base_mapdata=base_mapdata)(func)

        @wraps(func)
        def inner_wrapped_func(request, *args, **kwargs):
            try:
                changeset = request.changeset
            except AttributeError:
                changeset = ChangeSet.get_for_request(request)
                request.changeset = changeset

            request_update_cache_key = kwargs.get("update_cache_key", None)
            actual_update_cache_key = changeset.raw_cache_key_without_changes

            kwargs.update({
                "update_cache_key": actual_update_cache_key,
                "update_cache_key_match": request_update_cache_key == actual_update_cache_key,
            })
            return func(request, *args, **kwargs)

        return inner_wrapped_func
    return inner_wrapper
