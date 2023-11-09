from django.urls import path

from c3nav.mesh.consumers import MeshConsumer, MeshUIConsumer
from c3nav.mesh.views.firmware import (FirmwareBuildDetailView, FirmwareDetailView, FirmwaresCurrentListView,
                                       FirmwaresListView)
from c3nav.mesh.views.messages import MeshMessageListView, MeshMessageSendingView, MeshMessageSendView
from c3nav.mesh.views.misc import MeshLogView
from c3nav.mesh.views.nodes import NodeDetailView, NodeEditView, NodeListView

urlpatterns = [
    path('', NodeListView.as_view(), name='mesh.nodes'),
    path('logs/', MeshLogView.as_view(), name='mesh.logs'),
    path('messages/', MeshMessageListView.as_view(), name='mesh.messages'),
    path('firmwares/', FirmwaresListView.as_view(), name='mesh.firmwares'),
    path('firmwares/current/', FirmwaresCurrentListView.as_view(), name='mesh.firmwares.current'),
    path('firmwares/<int:pk>/', FirmwareDetailView.as_view(), name='mesh.firmwares.detail'),
    path('firmwares/builds/<int:pk>/', FirmwareBuildDetailView.as_view(), name='mesh.firmwares.build.detail'),
    path('<str:pk>/', NodeDetailView.as_view(), name='mesh.node.detail'),
    path('<str:pk>/edit/', NodeEditView.as_view(), name='mesh.node.edit'),
    path('message/sending/<uuid:uuid>/', MeshMessageSendingView.as_view(), name='mesh.sending'),
    path('message/<str:recipient>/<str:msg_type>/', MeshMessageSendView.as_view(), name='mesh.send'),
    path('message/<str:msg_type>/', MeshMessageSendView.as_view(), name='mesh.send'),
]

websocket_urlpatterns = [
    path('ws', MeshConsumer.as_asgi()),
    path('ui/ws', MeshUIConsumer.as_asgi()),
]
