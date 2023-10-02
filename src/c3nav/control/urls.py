from django.urls import path

from c3nav.control.views import (announcement_detail, announcement_list, grant_access, grant_access_qr, main_index,
                                 map_updates, user_detail, user_list, mesh_node_list)

urlpatterns = [
    path('users/', user_list, name='control.users'),
    path('users/<int:user>/', user_detail, name='control.users.detail'),
    path('access/', grant_access, name='control.access'),
    path('access/<str:token>', grant_access_qr, name='control.access.qr'),
    path('announcements/', announcement_list, name='control.announcements'),
    path('announcements/<int:annoucement>/', announcement_detail, name='control.announcements.detail'),
    path('mapupdates/', map_updates, name='control.map_updates'),
    path('mesh/', mesh_node_list, name='control.mesh_nodes'),
    path('', main_index, name='control.index'),
]
