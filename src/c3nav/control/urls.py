from django.conf.urls import url

from c3nav.control.views import (announcement_detail, announcement_list, grant_access, grant_access_qr, main_index,
                                 user_detail, user_list)

urlpatterns = [
    url(r'^users/$', user_list, name='control.users'),
    url(r'^users/(?P<user>\d+)/$', user_detail, name='control.users.detail'),
    url(r'^access/$', grant_access, name='control.access'),
    url(r'^access/(?P<token>[^/]+)$', grant_access_qr, name='control.access.qr'),
    url(r'^announcements/$', announcement_list, name='control.announcements'),
    url(r'^announcements/(?P<announcement>\d+)/$', announcement_detail, name='control.announcements.detail'),
    url(r'^$', main_index, name='control.index'),
]
