from contextlib import suppress

from django.conf import settings
from django.conf.urls import include, url
from django.contrib import admin

import c3nav.api.urls
import c3nav.editor.urls
import c3nav.mapdata.urls
import c3nav.site.urls

urlpatterns = [
    url(r'^editor/', include(c3nav.editor.urls)),
    url(r'^api/', include(c3nav.api.urls, namespace='api')),
    url(r'^map/', include(c3nav.mapdata.urls)),
    url(r'^admin/', admin.site.urls),
    url(r'^locales/', include('django.conf.urls.i18n')),
    url(r'^', include(c3nav.site.urls)),
]

if settings.DEBUG:
    with suppress(ImportError):
        import debug_toolbar
        urlpatterns.insert(0, url(r'^__debug__/', include(debug_toolbar.urls)))
