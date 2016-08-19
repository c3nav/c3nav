from django.conf.urls import include, url
from django.contrib import admin

from .control import urls as control_urls
from .mapdata import urls as map_urls

urlpatterns = [
    url(r'^control/', include(control_urls)),
    url(r'^map/', include(map_urls)),
    url(r'^admin/', admin.site.urls),
]
