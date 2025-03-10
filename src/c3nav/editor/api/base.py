from functools import wraps

from c3nav.editor.models import ChangeSet
from c3nav.mapdata.api.base import api_etag
from c3nav.mapdata.permissions import active_map_permissions


def api_etag_with_update_cache_key(permissions=True, etag_func=active_map_permissions.etag_func, base_mapdata=False):

    def inner_wrapper(func):
        func = api_etag(permissions=permissions, etag_func=etag_func, base_mapdata=base_mapdata)(func)

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
