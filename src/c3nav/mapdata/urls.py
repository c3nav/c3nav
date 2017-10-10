from django.conf.urls import url

from c3nav.mapdata.views import tile

urlpatterns = [
    url(r'^(?P<level>\d+)/(?P<zoom>\d+)/(?P<x>-?\d+)/(?P<y>-?\d+).(?P<format>png|svg)$', tile, name='mapdata.tile'),
]
