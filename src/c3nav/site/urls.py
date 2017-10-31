from django.conf.urls import url

from c3nav.site.views import map_index

pos = r'(@(?P<level>[a-z0-9-_:]+),(?P<x>-?\d+(\.\d+)?),(?P<y>-?\d+(\.\d+)?),(?P<zoom>-?\d+(\.\d+)?))?'

urlpatterns = [
    url(r'^r/(?P<origin>([a-z0-9-_:]+)?)/(?P<destination>([a-z0-9-_:]+)?)/%s$' % pos, map_index, name='site.index'),
    url(r'^l/(?P<destination>[a-z0-9-_:]+)/%s$' % pos, map_index, name='site.index'),
    url(r'^%s$' % pos, map_index, name='site.index')
]
