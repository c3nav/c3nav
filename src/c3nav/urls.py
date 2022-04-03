from contextlib import suppress

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

import c3nav.api.urls
import c3nav.control.urls
import c3nav.editor.urls
import c3nav.mapdata.urls
import c3nav.site.urls

urlpatterns = [
    path('editor/', include(c3nav.editor.urls)),
    path('api/', include((c3nav.api.urls, 'api'), namespace='api')),
    path('map/', include(c3nav.mapdata.urls)),
    path('admin/', admin.site.urls),
    path('control/', include(c3nav.control.urls)),
    path('locales/', include('django.conf.urls.i18n')),
    path('', include(c3nav.site.urls)),
]

if settings.DEBUG:
    with suppress(ImportError):
        import debug_toolbar
        urlpatterns.insert(0, path('__debug__/', include(debug_toolbar.urls)))
