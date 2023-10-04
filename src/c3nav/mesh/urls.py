from django.urls import path

from c3nav.mesh.consumers import MeshConsumer, MeshUIConsumer

websocket_urlpatterns = [
    path('ws', MeshConsumer.as_asgi()),
    path('ui/ws', MeshUIConsumer.as_asgi()),
]
