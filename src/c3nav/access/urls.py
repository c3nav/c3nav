from django.conf.urls import url
from django.contrib.auth import views as auth_views

from c3nav.access.views import activate_token, dashboard, prove, show_user_token, user_detail, user_list

urlpatterns = [
    url(r'^$', dashboard, name='access.dashboard'),
    url(r'^prove/$', prove, name='access.prove'),
    url(r'^activate/(?P<pk>[0-9]+):(?P<secret>[a-zA-Z0-9]+)/$', activate_token, name='access.activate'),
    url(r'^users/$', user_list, name='access.users'),
    url(r'^users/(?P<page>[0-9]+)/$', user_list, name='access.users'),
    url(r'^user/(?P<pk>[0-9]+)/$', user_detail, name='access.user'),
    url(r'^user/(?P<user>[0-9]+)/(?P<token>[0-9]+)/$', show_user_token, name='access.user.token'),
    url(r'^login/$', auth_views.login, {'template_name': 'access/login.html'}, name='access.login'),
    url(r'^logout/$', auth_views.logout, name='access.logout'),
]
