from django.conf import settings
from django.urls import path
from django.views.generic.base import RedirectView

from c3nav.api.api import auth_api_router
from c3nav.api.ninja import ninja_api
from c3nav.api.settings import settings_api_router
from c3nav.api.stats import stats_api_router
from c3nav.editor.api.endpoints import editor_api_router
from c3nav.mapdata.api.map import map_api_router
from c3nav.mapdata.api.mapdata import mapdata_api_router
from c3nav.mapdata.api.updates import updates_api_router
from c3nav.routing.api.positioning import positioning_api_router
from c3nav.routing.api.routing import routing_api_router

"""
new API (v2)
"""
ninja_api.add_router("/auth/", auth_api_router)
ninja_api.add_router("/updates/", updates_api_router)
ninja_api.add_router("/map/", map_api_router)
ninja_api.add_router("/routing/", routing_api_router)
ninja_api.add_router("/positioning/", positioning_api_router)
ninja_api.add_router("/mapdata/", mapdata_api_router)
ninja_api.add_router("/editor/", editor_api_router)
ninja_api.add_router("/settings/", settings_api_router)
ninja_api.add_router("/stats/", stats_api_router)
if settings.ENABLE_MESH:
    from c3nav.mesh.api import mesh_api_router
    ninja_api.add_router("/mesh/", mesh_api_router)


urlpatterns = [
    path('v2/', ninja_api.urls),
    path('', RedirectView.as_view(pattern_name="api-v2:openapi-view")),
]
