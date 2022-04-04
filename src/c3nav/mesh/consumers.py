from channels.generic.websocket import AsyncWebsocketConsumer

from c3nav.mesh import messages


class MeshConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()

    async def disconnect(self, close_code):
        pass

    async def receive(self, text_data=None, bytes_data=None):
        if bytes_data is None:
            return
        msg = messages.Message.decode(bytes_data)
        print('Received message:', msg)
        if isinstance(msg, messages.MeshSigninMessage):
            await self.send(messages.MeshLayerAnnounceMessage(messages.NO_LAYER).encode())
