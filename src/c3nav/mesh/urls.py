from django.urls import path

from c3nav.mesh.consumers import MeshConsumer

websocket_urlpatterns = [
    path('ws', MeshConsumer.as_asgi()),
]
