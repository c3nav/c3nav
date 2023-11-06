from django.urls import path

from c3nav.control.views.access import grant_access, grant_access_qr
from c3nav.control.views.announcements import announcement_detail, announcement_list
from c3nav.control.views.base import ControlPanelIndexView
from c3nav.control.views.mapupdates import map_updates
from c3nav.control.views.mesh import (MeshFirmwaresListView, MeshLogView, MeshMessageListView, MeshMessageSendingView,
                                      MeshMessageSendView, MeshNodeDetailView, MeshNodeEditView, MeshNodeListView)
from c3nav.control.views.users import UserListView, user_detail

urlpatterns = [
    path('users/', UserListView.as_view(), name='control.users'),
    path('users/<int:user>/', user_detail, name='control.users.detail'),
    path('access/', grant_access, name='control.access'),
    path('access/<str:token>', grant_access_qr, name='control.access.qr'),
    path('announcements/', announcement_list, name='control.announcements'),
    path('announcements/<int:annoucement>/', announcement_detail, name='control.announcements.detail'),
    path('mapupdates/', map_updates, name='control.map_updates'),
    path('mesh/', MeshNodeListView.as_view(), name='control.mesh.nodes'),
    path('mesh/logs/', MeshLogView.as_view(), name='control.mesh.log'),
    path('mesh/messages/', MeshMessageListView.as_view(), name='control.mesh.messages'),
    path('mesh/firmwares/', MeshFirmwaresListView.as_view(), name='control.mesh.firmwares'),
    path('mesh/<str:pk>/', MeshNodeDetailView.as_view(), name='control.mesh.node.detail'),
    path('mesh/<str:pk>/edit/', MeshNodeEditView.as_view(), name='control.mesh.node.edit'),
    path('mesh/message/sending/<uuid:uuid>/', MeshMessageSendingView.as_view(), name='control.mesh.sending'),
    path('mesh/message/<str:recipient>/<str:msg_type>/', MeshMessageSendView.as_view(), name='control.mesh.send'),
    path('mesh/message/<str:msg_type>/', MeshMessageSendView.as_view(), name='control.mesh.send'),
    path('', ControlPanelIndexView.as_view(), name='control.index'),
]
