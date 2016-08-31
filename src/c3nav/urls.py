from django.conf.urls import include, url
from django.contrib import admin

from .control import urls as control_urls
from .editor import urls as editor_urls

urlpatterns = [
    url(r'^control/', include(control_urls)),
    url(r'^editor/', include(editor_urls)),
    url(r'^admin/', admin.site.urls),
]
