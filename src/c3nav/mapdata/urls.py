from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^sources/(?P<filename>[^/]+)$', views.source, name='map.source'),
]
