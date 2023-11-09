from django.urls import path

from c3nav.control.views.access import grant_access, grant_access_qr
from c3nav.control.views.announcements import announcement_detail, announcement_list
from c3nav.control.views.base import ControlPanelIndexView
from c3nav.control.views.mapupdates import map_updates
from c3nav.control.views.users import UserListView, user_detail

urlpatterns = [
    path('users/', UserListView.as_view(), name='control.users'),
    path('users/<int:user>/', user_detail, name='control.users.detail'),
    path('access/', grant_access, name='control.access'),
    path('access/<str:token>', grant_access_qr, name='control.access.qr'),
    path('announcements/', announcement_list, name='control.announcements'),
    path('announcements/<int:announcement>/', announcement_detail, name='control.announcements.detail'),
    path('mapupdates/', map_updates, name='control.map_updates'),
    path('', ControlPanelIndexView.as_view(), name='control.index'),
]
