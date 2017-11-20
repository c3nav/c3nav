from django.conf.urls import url

from c3nav.mapdata.views import cache_package, history, tile, tile_access

urlpatterns = [
    url(r'^(?P<level>\d+)/(?P<zoom>\d+)/(?P<x>-?\d+)/(?P<y>-?\d+).png$', tile, name='mapdata.tile'),
    url(r'^history/(?P<level>\d+)/(?P<mode>base|composite).(?P<format>png|data)$', history, name='mapdata.history'),
    url(r'^cache/package(?P<filetype>\.tar|\.tar\.gz|\.tar\.xz)$', cache_package, name='mapdata.cache_package'),
    url(r'^tile_access$', tile_access, name='mapdata.tile_access'),
]
