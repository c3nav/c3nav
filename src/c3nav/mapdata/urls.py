from django.conf.urls import url

from c3nav.mapdata.views import get_cache_package, map_history, tile

urlpatterns = [
    url(r'^(?P<level>\d+)/(?P<zoom>-?\d+)/(?P<x>-?\d+)/(?P<y>-?\d+).png$', tile, name='mapdata.tile'),
    url(r'^(?P<level>\d+)/(?P<zoom>-?\d+)/(?P<x>-?\d+)/(?P<y>-?\d+)/(?P<access_permissions>\d+(-\d+)*).png$', tile,
        name='mapdata.tile'),
    url(r'^history/(?P<level>\d+)/(?P<mode>base|composite)\.(?P<filetype>png|data)$', map_history,
        name='mapdata.map_history'),
    url(r'^cache/package\.(?P<filetype>tar|tar\.gz|tar\.xz)$', get_cache_package, name='mapdata.cache_package'),
]
