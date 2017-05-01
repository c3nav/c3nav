import re
from collections import OrderedDict

from compressor.utils.decorators import cached_property
from django.conf.urls import include, url
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter

from c3nav.mapdata.api import GeometryTypeViewSet, GeometryViewSet, LevelViewSet, LocationViewSet, SourceViewSet

router = SimpleRouter()
router.register(r'levels', LevelViewSet)
router.register(r'sources', SourceViewSet)

router.register(r'geometrytypes', GeometryTypeViewSet, base_name='geometrytype')
router.register(r'geometries', GeometryViewSet, base_name='geometry')

router.register(r'locations', LocationViewSet, base_name='location')


class APIRoot(GenericAPIView):
    """
    Welcome to the c3nav RESTful API.
    """

    def _format_pattern(self, pattern):
        return re.sub(r'\(\?P<([^>]*[^>_])_?>[^)]+\)', r'{\1}', pattern)[1:-1]

    @cached_property
    def urls(self):
        urls = OrderedDict()
        for urlpattern in router.urls:
            name = urlpattern.name
            url = self._format_pattern(urlpattern.regex.pattern)
            base = url.split('/', 1)[0]
            if '-' in name:
                urls.setdefault(base, OrderedDict())[name.split('-', 1)[1]] = url
            else:
                urls[name] = url
        return urls

    def get(self, request):
        return Response(self.urls)


urlpatterns = [
    url(r'^$', APIRoot.as_view()),
    url(r'', include(router.urls)),
]
