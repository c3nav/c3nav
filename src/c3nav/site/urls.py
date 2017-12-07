from django.conf.urls import url

from c3nav.site.views import account_view, login_view, logout_view, map_index, qr_code, register_view

slug = r'(?P<slug>[a-z0-9-_.:]+)'
slug2 = r'(?P<slug2>[a-z0-9-_.:]+)'
details = r'(?P<details>details/)?'
pos = r'(@(?P<level>[a-z0-9-_:]+),(?P<x>-?\d+(\.\d+)?),(?P<y>-?\d+(\.\d+)?),(?P<zoom>-?\d+(\.\d+)?))?'
embed = r'(?P<embed>embed/)?'

urlpatterns = [
    url(r'^%s(?P<mode>[l])/%s/%s%s$' % (embed, slug, details, pos), map_index, name='site.index'),
    url(r'^%s(?P<mode>[od])/%s/%s$' % (embed, slug, pos), map_index, name='site.index'),
    url(r'^%sr/%s/%s/%s%s$' % (embed, slug, slug2, details, pos), map_index, name='site.index'),
    url(r'^%s(?P<mode>r)/%s$' % (embed, pos), map_index, name='site.index'),
    url(r'^%s$' % pos, map_index, name='site.index'),
    url(r'^qr/(?P<path>.*)$', qr_code, name='site.qr'),
    url(r'^login$', login_view, name='site.login'),
    url(r'^logout$', logout_view, name='site.logout'),
    url(r'^register$', register_view, name='site.register'),
    url(r'^account/$', account_view, name='site.account'),
]
