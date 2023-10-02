from django.urls import path

from c3nav.control.views import (announcement_detail, announcement_list, grant_access, grant_access_qr, map_updates,
                                 user_detail, MeshNodeListView, ControlPanelIndexView,
                                 UserListView)

urlpatterns = [
    path('users/', UserListView.as_view(), name='control.users'),
    path('users/<int:user>/', user_detail, name='control.users.detail'),
    path('access/', grant_access, name='control.access'),
    path('access/<str:token>', grant_access_qr, name='control.access.qr'),
    path('announcements/', announcement_list, name='control.announcements'),
    path('announcements/<int:annoucement>/', announcement_detail, name='control.announcements.detail'),
    path('mapupdates/', map_updates, name='control.map_updates'),
    path('mesh/', MeshNodeListView.as_view(), name='control.mesh_nodes'),
    path('', ControlPanelIndexView.as_view(), name='control.index'),
]
