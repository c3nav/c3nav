from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^$', views.index, name='editor.index'),
    url(r'^sources/image/(?P<source>[^/]+)$', views.source, name='editor.sources.image'),
]
