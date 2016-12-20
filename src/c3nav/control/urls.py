from django.conf.urls import url
from django.contrib.auth import views as auth_views

from c3nav.control.views import dashboard, prove

urlpatterns = [
    url(r'^$', dashboard, name='control.dashboard'),
    url(r'^prove/$', prove, name='control.prove'),
    url(r'^login/$', auth_views.login, {'template_name': 'control/login.html'}, name='site.login'),
    url(r'^logout/$', auth_views.logout, name='site.logout'),
]
