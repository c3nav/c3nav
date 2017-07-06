import re
from collections import OrderedDict

from compressor.utils.decorators import cached_property
from django.conf.urls import include, url
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter

from c3nav.editor.api import ChangeSetViewSet, EditorViewSet
from c3nav.mapdata.api import (AreaViewSet, BuildingViewSet, ColumnViewSet, DoorViewSet, HoleViewSet, LevelViewSet,
                               LineObstacleViewSet, LocationGroupViewSet, LocationViewSet, ObstacleViewSet,
                               PointViewSet, SourceViewSet, SpaceViewSet, StairViewSet)

router = SimpleRouter()
router.register(r'levels', LevelViewSet)
router.register(r'buildings', BuildingViewSet)
router.register(r'spaces', SpaceViewSet)
router.register(r'doors', DoorViewSet)
router.register(r'holes', HoleViewSet)
router.register(r'areas', AreaViewSet)
router.register(r'stairs', StairViewSet)
router.register(r'obstacles', ObstacleViewSet)
router.register(r'lineobstacles', LineObstacleViewSet)
router.register(r'columns', ColumnViewSet)
router.register(r'points', PointViewSet)
router.register(r'sources', SourceViewSet)

router.register(r'locations', LocationViewSet)
router.register(r'locationgroups', LocationGroupViewSet)

router.register(r'editor', EditorViewSet, base_name='editor')
router.register(r'changesets', ChangeSetViewSet)


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
            url = self._format_pattern(urlpattern.regex.pattern).replace('{pk}', '{id}')
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
