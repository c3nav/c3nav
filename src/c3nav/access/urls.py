from django.conf.urls import url
from django.contrib.auth import views as auth_views

from c3nav.access.views import activate_token, dashboard, prove

urlpatterns = [
    url(r'^$', dashboard, name='access.dashboard'),
    url(r'^prove/$', prove, name='access.prove'),
    url(r'^activate/(?P<pk>[0-9]+):(?P<secret>[a-zA-Z0-9]+)/$', activate_token, name='access.activate'),
    url(r'^login/$', auth_views.login, {'template_name': 'access/login.html'}, name='access.login'),
    url(r'^logout/$', auth_views.logout, name='access.logout'),
]
