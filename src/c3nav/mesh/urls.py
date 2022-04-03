from django.urls import path

from c3nav.mesh.consumers import EchoConsumer

websocket_urlpatterns = [
    path('ws', EchoConsumer.as_asgi()),
]
