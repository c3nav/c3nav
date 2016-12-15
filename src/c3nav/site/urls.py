from django.conf.urls import url

from c3nav.site.views import main

urlpatterns = [
    url(r'^(?P<origin>[a-z0-9-_:]+)/$', main, name='site.main'),
    url(r'^_/(?P<destination>[a-z0-9-_:]+)/$', main, name='site.main'),
    url(r'^(?P<origin>[a-z0-9-_:]+)/(?P<destination>[a-z0-9-_:]+)/$', main, name='site.main'),
    url(r'^$', main, name='site.main')
]
