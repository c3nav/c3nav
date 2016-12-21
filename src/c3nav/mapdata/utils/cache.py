from calendar import timegm
from collections import OrderedDict
from functools import wraps

from django.core.cache import cache
from django.utils.http import http_date
from rest_framework.response import Response as APIResponse
from rest_framework.views import APIView

from c3nav.mapdata.lastupdate import get_last_mapdata_update


def cache_result(cache_key, timeout=900):
    def decorator(func):
        @wraps(func)
        def inner(*args, **kwargs):
            last_update = get_last_mapdata_update()
            if last_update is None:
                return func(*args, **kwargs)

            result = cache.get(cache_key)
            if not result:
                result = func(*args, **kwargs)
                cache.set(cache_key, result, timeout)
            return result
        return inner
    return decorator


def cache_mapdata_api_response(timeout=900):
    def decorator(func):
        @wraps(func)
        def inner(self, request, *args, add_cache_key=None, **kwargs):
            last_update = get_last_mapdata_update()
            if last_update is None:
                return func(self, request, *args, **kwargs)

            cache_key = '__'.join((
                'c3nav__mapdata__api',
                last_update.isoformat(),
                add_cache_key if add_cache_key is not None else '',
                request.accepted_renderer.format if isinstance(self, APIView) else '',
                request.path,
            ))

            response = cache.get(cache_key)
            if not response:
                response = func(self, request, *args, **kwargs)
                response['Last-Modifed'] = http_date(timegm(last_update.utctimetuple()))
                if isinstance(response, APIResponse):
                    response = self.finalize_response(request, response, *args, **kwargs)
                    response.render()
                if response.status_code < 400:
                    cache.set(cache_key, response, timeout)

            return response
        return inner
    return decorator


class CachedReadOnlyViewSetMixin():
    include_package_access = False

    def _get_unlocked_packages_ids(self, request):
        from c3nav.access.apply import get_unlocked_packages
        return ','.join(str(i) for i in sorted(package.id for package in get_unlocked_packages(request)))

    def _get_add_cache_key(self, request, add_cache_key=''):
        cache_key = add_cache_key
        if self.include_package_access:
            cache_key += '__'+self._get_unlocked_packages_ids(request)
        return cache_key

    def list(self, request, *args, **kwargs):
        kwargs['add_cache_key'] = self._get_add_cache_key(request, kwargs.get('add_cache_key', ''))
        return self._list(request, *args, **kwargs)

    @cache_mapdata_api_response()
    def _list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        kwargs['add_cache_key'] = self._get_add_cache_key(request, kwargs.get('add_cache_key', ''))
        return self._retrieve(request, *args, **kwargs)

    @cache_mapdata_api_response()
    def _retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)


@cache_result('c3nav__mapdata__levels')
def get_levels_cached():
    from c3nav.mapdata.models import Level
    return OrderedDict((level.name, level) for level in Level.objects.all())


@cache_result('c3nav__mapdata__packages')
def get_packages_cached():
    from c3nav.mapdata.models import Package
    return {package.name: package for package in Package.objects.all()}
