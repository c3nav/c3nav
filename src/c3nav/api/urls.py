from django.conf.urls import include, url
from rest_framework.routers import DefaultRouter

from c3nav.editor.api import HosterViewSet
from c3nav.mapdata.api import FeatureTypeViewSet, FeatureViewSet, LevelViewSet, PackageViewSet, SourceViewSet

router = DefaultRouter()
router.register(r'levels', LevelViewSet)
router.register(r'packages', PackageViewSet)
router.register(r'sources', SourceViewSet)
router.register(r'featuretypes', FeatureTypeViewSet, base_name='featuretype')
router.register(r'features', FeatureViewSet)
router.register(r'hosters', HosterViewSet, base_name='hoster')


urlpatterns = [
    url(r'^(?P<version>v\d+)/', include(router.urls, namespace='v1')),
]
