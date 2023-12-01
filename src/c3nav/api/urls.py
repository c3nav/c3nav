import inspect
import re
from collections import OrderedDict

from django.urls import include, path, re_path
from django.utils.functional import cached_property
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter

from c3nav.api.api import SessionViewSet
from c3nav.api.newapi import auth_api_router
from c3nav.api.ninja import ninja_api
from c3nav.editor.api import ChangeSetViewSet, EditorViewSet
from c3nav.editor.newapi.endpoints import editor_api_router
from c3nav.mapdata.api import (AccessRestrictionGroupViewSet, AccessRestrictionViewSet, AreaViewSet, BuildingViewSet,
                               ColumnViewSet, CrossDescriptionViewSet, DoorViewSet, DynamicLocationPositionViewSet,
                               HoleViewSet, LeaveDescriptionViewSet, LevelViewSet, LineObstacleViewSet,
                               LocationBySlugViewSet, LocationGroupCategoryViewSet, LocationGroupViewSet,
                               LocationViewSet, MapViewSet, ObstacleViewSet, POIViewSet, RampViewSet, SourceViewSet,
                               SpaceViewSet, StairViewSet, UpdatesViewSet)
from c3nav.mapdata.newapi.map import map_api_router
from c3nav.mapdata.newapi.mapdata import mapdata_api_router
from c3nav.mapdata.utils.user import can_access_editor
from c3nav.mesh.newapi import mesh_api_router
from c3nav.routing.api import RoutingViewSet
from c3nav.routing.newapi.positioning import positioning_api_router
from c3nav.routing.newapi.routing import routing_api_router

"""
new API (v2)
"""
ninja_api.add_router("/auth/", auth_api_router)
ninja_api.add_router("/map/", map_api_router)
ninja_api.add_router("/routing/", routing_api_router)
ninja_api.add_router("/positioning/", positioning_api_router)
ninja_api.add_router("/mapdata/", mapdata_api_router)
ninja_api.add_router("/editor/", editor_api_router)
ninja_api.add_router("/mesh/", mesh_api_router)


"""
legacy API
"""
router = SimpleRouter()

router.register(r'map', MapViewSet, basename='map')
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
router.register(r'locations/by_slug', LocationBySlugViewSet, basename='location-by-slug')
router.register(r'locations/dynamic', DynamicLocationPositionViewSet, basename='dynamic-location')
router.register(r'locationgroupcategories', LocationGroupCategoryViewSet)
router.register(r'locationgroups', LocationGroupViewSet)

router.register(r'updates', UpdatesViewSet, basename='updates')

router.register(r'routing', RoutingViewSet, basename='routing')

router.register(r'editor', EditorViewSet, basename='editor')
router.register(r'changesets', ChangeSetViewSet)
router.register(r'session', SessionViewSet, basename='session')



class APIRoot(GenericAPIView):
    """
    Welcome to the c3nav RESTful API.
    The HTML preview is only shown because your Browser sent text/html in its Accept header.
    If you want to use this API on a large scale, please use a client that supports E-Tags.
    For more information on a specific API endpoint, access it with a browser.

    This is the old API which is slowly being phased out in favor of the new API at /api/v2/.
    """

    def _format_pattern(self, pattern):
        return re.sub(r'\(\?P<([^>]*[^>_])_?>[^)]+\)', r'{\1}', pattern)[1:-1]

    @cached_property
    def urls(self):
        include_editor = can_access_editor(self.request)
        urls: dict[str, dict[str, str] | str] = OrderedDict()
        for urlpattern in router.urls:
            if not include_editor and inspect.getmodule(urlpattern.callback).__name__.startswith('c3nav.editor.'):
                continue
            name = urlpattern.name
            url = self._format_pattern(str(urlpattern.pattern)).replace('{pk}', '{id}')
            base = url.split('/', 1)[0]
            if base == 'editor':
                if name == 'editor-list':
                    continue
                if name == 'editor-detail':
                    name = 'editor-api'
            elif base == 'session':
                if name == 'session-list':
                    name = 'session-info'
            if '-' in name:
                urls.setdefault(base, OrderedDict())[name.split('-', 1)[1]] = url
            else:
                urls[name] = url
        return urls

    def get(self, request):
        return Response(self.urls)


urlpatterns = [
    # todo: does this work? can it be better?
    re_path(r'^$', APIRoot.as_view()),
    path('', include(router.urls)),
]
