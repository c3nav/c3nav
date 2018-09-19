import inspect
import re
from collections import OrderedDict

from django.conf.urls import include, url
from django.utils.functional import cached_property
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter

from c3nav.editor.api import ChangeSetViewSet, EditorViewSet
from c3nav.mapdata.api import (AccessRestrictionGroupViewSet, AccessRestrictionViewSet, AreaViewSet, BuildingViewSet,
                               ColumnViewSet, CrossDescriptionViewSet, DoorViewSet, HoleViewSet,
                               LeaveDescriptionViewSet, LevelViewSet, LineObstacleViewSet, LocationBySlugViewSet,
                               LocationGroupCategoryViewSet, LocationGroupViewSet, LocationViewSet, MapViewSet,
                               ObstacleViewSet, POIViewSet, RampViewSet, SourceViewSet, SpaceViewSet, StairViewSet,
                               UpdatesViewSet)
from c3nav.mapdata.utils.user import can_access_editor
from c3nav.routing.api import RoutingViewSet

router = SimpleRouter()
router.register(r'map', MapViewSet, base_name='map')
router.register(r'levels', LevelViewSet)
router.register(r'buildings', BuildingViewSet)
router.register(r'spaces', SpaceViewSet)
router.register(r'doors', DoorViewSet)
router.register(r'holes', HoleViewSet)
router.register(r'areas', AreaViewSet)
router.register(r'stairs', StairViewSet)
router.register(r'ramps', RampViewSet)
router.register(r'obstacles', ObstacleViewSet)
router.register(r'lineobstacles', LineObstacleViewSet)
router.register(r'columns', ColumnViewSet)
router.register(r'pois', POIViewSet)
router.register(r'leavedescriptions', LeaveDescriptionViewSet)
router.register(r'crossdescriptions', CrossDescriptionViewSet)
router.register(r'sources', SourceViewSet)
router.register(r'accessrestrictions', AccessRestrictionViewSet)
router.register(r'accessrestrictiongroups', AccessRestrictionGroupViewSet)

router.register(r'locations', LocationViewSet)
router.register(r'locations/by_slug', LocationBySlugViewSet, base_name='location-by-slug')
router.register(r'locationgroupcategories', LocationGroupCategoryViewSet)
router.register(r'locationgroups', LocationGroupViewSet)

router.register(r'updates', UpdatesViewSet, base_name='updates')

router.register(r'routing', RoutingViewSet, base_name='routing')

router.register(r'editor', EditorViewSet, base_name='editor')
router.register(r'changesets', ChangeSetViewSet)


class APIRoot(GenericAPIView):
    """
    Welcome to the c3nav RESTful API.
    The HTML preview is only shown because your Browser sent text/html in its Accept header.
    If you want to use this API on a large scale, please use a client that supports E-Tags.
    For more information on a specific API endpoint, access it with a browser.
    """

    def _format_pattern(self, pattern):
        return re.sub(r'\(\?P<([^>]*[^>_])_?>[^)]+\)', r'{\1}', pattern)[1:-1]

    @cached_property
    def urls(self):
        include_editor = can_access_editor(self.request)
        urls = OrderedDict()
        for urlpattern in router.urls:
            if not include_editor and inspect.getmodule(urlpattern.callback).__name__.startswith('c3nav.editor.'):
                continue
            name = urlpattern.name
            url = self._format_pattern(str(urlpattern.pattern)).replace('{pk}', '{id}')
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
