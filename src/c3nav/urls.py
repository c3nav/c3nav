from django.conf.urls import include, url
from django.contrib import admin

import c3nav.api.urls
import c3nav.control.urls
import c3nav.editor.urls
import c3nav.site.urls

urlpatterns = [
    url(r'^control/', include(c3nav.control.urls)),
    url(r'^editor/', include(c3nav.editor.urls)),
    url(r'^api/', include(c3nav.api.urls, namespace='api')),
    url(r'^admin/', admin.site.urls),
    url(r'^', include(c3nav.site.urls)),
]
