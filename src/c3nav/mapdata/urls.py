from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^sources/(?P<source>[^/]+)$', views.source, name='map.source'),
    url(r'^data/add$', views.source, name='map.edit.source'),
]
