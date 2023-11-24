import json
from functools import wraps

from django.core.serializers.json import DjangoJSONEncoder
from django.utils.cache import get_conditional_response
from django.utils.http import quote_etag
from django.utils.translation import get_language
from ninja.decorators import decorate_view

from c3nav.mapdata.api import api_stats_clean_location_value
from c3nav.mapdata.models import MapUpdate
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.models.geometry.base import GeometryMixin
from c3nav.mapdata.utils.cache.local import LocalCacheProxy
from c3nav.mapdata.utils.cache.stats import increment_cache_key

request_cache = LocalCacheProxy(maxsize=64)


def newapi_etag(permissions=True, etag_func=AccessPermission.etag_func, base_mapdata=False):

    def outer_wrapper(func):
        @wraps(func)
        def outer_wrapped_func(request, *args, **kwargs):
            response = func(request, *args, **kwargs)
            if response.status_code == 200:
                if request._target_etag:
                    response['ETag'] = request._target_etag
                response['Cache-Control'] = 'no-cache'
                if request._target_cache_key:
                    request_cache.set(request._target_cache_key, response, 900)
            return response
        return outer_wrapped_func

    def inner_wrapper(func):
        @wraps(func)
        def inner_wrapped_func(request, *args, **kwargs):
            # calculate the ETag
            response_format = "json"
            raw_etag = '%s:%s:%s' % (response_format, get_language(),
                                     (etag_func(request) if permissions else MapUpdate.current_cache_key()))
            if base_mapdata:
                raw_etag += ':%d' % request.user_permissions.can_access_base_mapdata
            etag = quote_etag(raw_etag)

            response = get_conditional_response(request, etag)
            if response:
                return response

            request._target_etag = etag

            # calculate the cache key
            data = {}
            for name, value in kwargs.items():
                try:
                    model_dump = value.model_dump
                except AttributeError:
                    pass
                else:
                    value = model_dump()
                data[name] = value
            cache_key = 'mapdata:api:%s:%s:%s' % (
                request.resolver_match.route.replace('/', '-').strip('-'),
                raw_etag,
                json.dumps(data, separators=(',', ':'), sort_keys=True, cls=DjangoJSONEncoder),
            )

            request._target_cache_key = cache_key

            response = request_cache.get(cache_key)
            if response is not None:
                return response

            with GeometryMixin.dont_keep_originals():
                return func(request, *args, **kwargs)

        return decorate_view(outer_wrapper)(inner_wrapped_func)
    return inner_wrapper


def newapi_stats(stat_name):
    def wrapper(func):
        @wraps(func)
        def wrapped_func(request, *args, **kwargs):
            response = func(request, *args, **kwargs)
            if response.status_code < 400 and kwargs:
                name, value = next(iter(kwargs.items()))
                for value in api_stats_clean_location_value(value):
                    increment_cache_key('apistats__%s__%s__%s' % (stat_name, name, value))
            return response
        return wrapped_func
    return decorate_view(wrapper)
