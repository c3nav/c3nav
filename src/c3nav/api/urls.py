from django.conf.urls import include, url
from rest_framework.routers import DefaultRouter

from .views import editor as editor_views
from .views import mapdata as mapdata_views

router = DefaultRouter()
router.register(r'levels', mapdata_views.LevelViewSet)
router.register(r'packages', mapdata_views.PackageViewSet)
router.register(r'sources', mapdata_views.SourceViewSet)
router.register(r'featuretypes', mapdata_views.FeatureTypeViewSet, base_name='featuretype')
router.register(r'features', editor_views.FeatureViewSet)
router.register(r'hosters', editor_views.HosterViewSet, base_name='hoster')


urlpatterns = [
    url(r'^(?P<version>v\d+)/', include(router.urls, namespace='v1')),
]
