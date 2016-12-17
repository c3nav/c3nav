from django.conf.urls import url

from c3nav.site.views import level_image, main

urlpatterns = [
    url(r'^map/(?P<level>[a-z0-9-_:]+).png$', level_image, name='site.level_image'),
    url(r'^(?P<origin>[a-z0-9-_:]+)/$', main, name='site.main'),
    url(r'^_/(?P<destination>[a-z0-9-_:]+)/$', main, name='site.main'),
    url(r'^(?P<origin>[a-z0-9-_:]+)/(?P<destination>[a-z0-9-_:]+)/$', main, name='site.main'),
    url(r'^$', main, name='site.main')
]
