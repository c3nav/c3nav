from django.conf.urls import include, url

from rest_framework.routers import DefaultRouter

from .views import map as map_views

router = DefaultRouter()
router.register(r'map/levels', map_views.LevelViewSet)
router.register(r'map/packages', map_views.PackageViewSet)
router.register(r'map/sources', map_views.SourceViewSet)


urlpatterns = [
    url(r'^(?P<version>v\d+)/', include(router.urls, namespace='v1')),
]
