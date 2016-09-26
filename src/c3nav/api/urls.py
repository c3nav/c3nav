from django.conf.urls import include, url
from rest_framework.routers import DefaultRouter

from ..editor import api as editor_api
from ..mapdata import api as mapdata_api

router = DefaultRouter()
router.register(r'levels', mapdata_api.LevelViewSet)
router.register(r'packages', mapdata_api.PackageViewSet)
router.register(r'sources', mapdata_api.SourceViewSet)
router.register(r'featuretypes', mapdata_api.FeatureTypeViewSet, base_name='featuretype')
router.register(r'features', mapdata_api.FeatureViewSet)
router.register(r'hosters', editor_api.HosterViewSet, base_name='hoster')


urlpatterns = [
    url(r'^(?P<version>v\d+)/', include(router.urls, namespace='v1')),
]
