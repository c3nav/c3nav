from contextlib import suppress

from channels.routing import URLRouter
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = []
websocket_urlpatterns = []

if settings.SERVE_ANYTHING:
    import c3nav.control.urls
    import c3nav.editor.urls
    import c3nav.mapdata.urls
    import c3nav.site.urls
    urlpatterns += [
        path('editor/', include(c3nav.editor.urls)),
        path('map/', include(c3nav.mapdata.urls)),
        path('admin/', admin.site.urls),
        path('control/', include(c3nav.control.urls)),
    ]

    if settings.SERVE_API:
        import c3nav.api.urls
        urlpatterns += [
            path('api/', include(c3nav.api.urls)),
        ]

    if settings.ENABLE_MESH:
        import c3nav.mesh.urls
        urlpatterns += [
            path('mesh/', include(c3nav.mesh.urls)),
        ]

    urlpatterns += [
        path('locales/', include('django.conf.urls.i18n')),
        path('', include(c3nav.site.urls)),
    ] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

    if settings.ENABLE_MESH:
        websocket_urlpatterns += [
            path('mesh/', URLRouter(c3nav.mesh.urls.websocket_urlpatterns)),
        ]

    if settings.DEBUG:
        with suppress(ImportError):
            import debug_toolbar
            urlpatterns.insert(0, path('__debug__/', include(debug_toolbar.urls)))

    if settings.METRICS:
        with suppress(ImportError):
            import django_prometheus  # noqu
            from c3nav.mapdata.views import prometheus_exporter
            urlpatterns += [
                path('prometheus/metrics', prometheus_exporter, name='prometheus-exporter'),
            ]

    if settings.SSO_ENABLED:
        urlpatterns += [
            path('sso/', include('social_django.urls', namespace='social'))
        ]
