import base64

from django.core.cache import cache
from django.template.response import SimpleTemplateResponse
from django.utils.cache import patch_vary_headers

from c3nav.mapdata.permissions import get_unlocked_packages


class CachedViewSetMixin:
    def get_cache_key(self, request):
        cache_key = ('api__' + ('OPTIONS' if request.method == 'OPTIONS' else 'GET') + '_' +
                     base64.b64encode(self.get_cache_params(request).encode()).decode() + '_' +
                     request.path + '?' + request.META['QUERY_STRING'])
        return cache_key

    def get_cache_params(self, request):
        return request.META.get('HTTP_ACCEPT', '')

    def dispatch(self, request, *args, **kwargs):
        do_cache = request.method in ('GET', 'HEAD', 'OPTIONS')
        if do_cache:
            cache_key = self.get_cache_key(request)
            if cache_key in cache:
                return cache.get(cache_key)
        response = super().dispatch(request, *args, **kwargs)
        patch_vary_headers(response, ['Cookie'])
        if do_cache:
            if isinstance(response, SimpleTemplateResponse):
                response.render()
            cache.set(cache_key, response, 60)
        return response

    @property
    def default_response_headers(self):
        headers = super().default_response_headers
        headers['Vary'] += ', Cookie'
        return headers


class AccessCachedViewSetMixin(CachedViewSetMixin):
    def get_cache_params(self, request):
        return super().get_cache_params(request) + '___' + '___'.join(get_unlocked_packages(request))
