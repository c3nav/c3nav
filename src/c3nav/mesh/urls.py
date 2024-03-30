from django.urls import path

from c3nav.mesh.consumers import MeshConsumer, MeshUIConsumer
from c3nav.mesh.views.firmware import (FirmwareBuildDetailView, FirmwareDetailView, FirmwaresCurrentListView,
                                       FirmwaresListView, OTADetailView, OTAListView)
from c3nav.mesh.views.messages import MeshMessageListView, MeshMessageSendingView, MeshMessageSendView
from c3nav.mesh.views.misc import MeshLogView, MeshRangingView
from c3nav.mesh.views.nodes import NodeDetailView, NodeListView

urlpatterns = [
    path('', NodeListView.as_view(), name='mesh.nodes'),
    path('logs/', MeshLogView.as_view(), name='mesh.logs'),
    path('messages/', MeshMessageListView.as_view(), name='mesh.messages'),
    path('firmwares/', FirmwaresListView.as_view(), name='mesh.firmwares'),
    path('firmwares/current/', FirmwaresCurrentListView.as_view(), name='mesh.firmwares.current'),
    path('firmwares/<int:pk>/', FirmwareDetailView.as_view(), name='mesh.firmwares.detail'),
    path('firmwares/builds/<int:pk>/', FirmwareBuildDetailView.as_view(), name='mesh.firmwares.build.detail'),
    path('ota/', OTAListView.as_view(), name='mesh.ota.list'),
    path('ota/all/', OTAListView.as_view(all=True), name='mesh.ota.list.all'),
    path('ota/<int:pk>/', OTADetailView.as_view(), name='mesh.ota.detail'),
    path('nodes/<str:pk>/', NodeDetailView.as_view(), name='mesh.node.detail'),
    path('message/sending/<uuid:uuid>/', MeshMessageSendingView.as_view(), name='mesh.sending'),
    path('message/<str:recipient>/<str:msg_type>/', MeshMessageSendView.as_view(), name='mesh.send'),
    path('message/<str:msg_type>/', MeshMessageSendView.as_view(), name='mesh.send'),
    path('ranging/', MeshRangingView.as_view(), name='mesh.ranging'),
]

websocket_urlpatterns = [
    path('ws', MeshConsumer.as_asgi()),
    path('ui/ws', MeshUIConsumer.as_asgi()),
]
