import json
import time
from functools import wraps
from typing import Optional, Callable

from django.conf import settings
from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Prefetch
from django.utils.cache import get_conditional_response
from django.utils.http import quote_etag
from django.utils.translation import get_language
from ninja.decorators import decorate_view

from c3nav.mapdata.models import AccessRestriction, MapUpdate
from c3nav.mapdata.models.geometry.base import GeometryMixin
from c3nav.mapdata.models.locations import SpecificLocation
from c3nav.mapdata.permissions import active_map_permissions
from c3nav.mapdata.utils.cache.proxied import LocalCacheProxy, VersionedCacheProxy
from c3nav.mapdata.utils.cache.stats import increment_cache_key


# todo: this ignores expire… so… hm?
request_cache = VersionedCacheProxy(LocalCacheProxy(maxsize=settings.CACHE_SIZE_API))


def api_etag(permissions=True, quests=False, cache_job_types: tuple[str, ...] = (),
             base_etag_func: Optional[Callable] = None, base_mapdata=False,
             etag_add_key: Optional[tuple[str, str]] = None):

    def outer_wrapper(func):
        @wraps(func)
        def outer_wrapped_func(request, *args, **kwargs):
            response = func(request, *args, **kwargs)
            if response.status_code == 200:
                if request._target_etag:
                    response['ETag'] = request._target_etag
                response['Cache-Control'] = 'no-cache'
                if request._target_cache_key:
                    request_cache.set(request._target_version, request._target_cache_key, response, 900)
            return response
        return outer_wrapped_func

    def inner_wrapper(func):
        @wraps(func)
        def inner_wrapped_func(request, *args, **kwargs):
            # calculate the ETag
            last_update = MapUpdate.last_update(*cache_job_types)

            # prefix will not be part of the etag, but part of the cache key
            etag_prefix = f"{last_update.cache_key}:" if base_etag_func is None else ""

            raw_etag = get_language()
            if base_etag_func:
                raw_etag += f":{base_etag_func(request)}"
            if permissions:
                raw_etag += f":{active_map_permissions.permissions_cache_key}"
            if quests:
                raw_etag += ':all' if request.user.is_superuser else f':{','.join(request.user_permissions.quests)}'
            if base_mapdata:
                raw_etag += f":{active_map_permissions.base_mapdata_cache_key}"

            if etag_add_key:
                # todo: we need a nicer solution for this oh my god
                etag_add_cache_key = (
                    f'mapdata:etag_add:{etag_add_key[1]}:{getattr(kwargs[etag_add_key[0]], etag_add_key[1])}'
                )
                etag_add = cache.get(etag_add_cache_key, None)
                if etag_add is None:
                    etag_add = int(time.time())
                    cache.set(etag_add_cache_key, etag_add, 300)
                raw_etag += ':%d' % etag_add

            etag = quote_etag(etag_prefix+raw_etag)

            response = get_conditional_response(request, etag)
            if response:
                return response

            request._target_version = last_update
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

            response = request_cache.get(last_update, cache_key)
            if response is not None:
                return response

            with GeometryMixin.dont_keep_originals():
                return func(request, *args, **kwargs)

        return decorate_view(outer_wrapper)(inner_wrapped_func)
    return inner_wrapper


def api_stats(stat_name):
    if settings.METRICS:
        from c3nav.mapdata.metrics import APIStatsCollector
        APIStatsCollector.add_stat(stat_name, ['by', 'query'])
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


def optimize_query(qs):
    # todo: get rid of this?
    if issubclass(qs.model, AccessRestriction):
        qs = qs.prefetch_related('groups')
    return qs


def api_stats_clean_location_value(value):
    if isinstance(value, str) and value.startswith('c:'):
        value = value.split(':')
        value = 'c:%s:%d:%d' % (value[1], int(float(value[2]) / 3) * 3, int(float(value[3]) / 3) * 3)
        return (value, 'c:anywhere')
    return (value, )
