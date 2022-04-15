import traceback

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from c3nav.mesh import messages
from c3nav.mesh.models import MeshNode, NodeMessage


class MeshConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        print('connected!')
        await self.accept()

    async def disconnect(self, close_code):
        print('disconnected!')
        pass

    async def send_msg(self, msg):
        print('Sending message:', msg)
        await self.send(bytes_data=msg.encode())

    async def receive(self, text_data=None, bytes_data=None):
        if bytes_data is None:
            return
        try:
            msg = messages.Message.decode(bytes_data)
        except Exception:
            traceback.print_exc()
            return

        if msg.dst != messages.ROOT_ADDRESS and msg.dst != messages.PARENT_ADDRESS:
            print('Received message for forwarding:', msg)
            # todo: this message isn't for us, forward it
            return

        print('Received message:', msg)
        node = await self.log_received_message(msg)  # noqa
        if isinstance(msg, messages.MeshSigninMessage):
            await self.send_msg(messages.MeshLayerAnnounceMessage(
                src=messages.ROOT_ADDRESS,
                dst=msg.src,
                layer=messages.NO_LAYER
            ))
            await self.send_msg(messages.ConfigDumpMessage(
                src=messages.ROOT_ADDRESS,
                dst=msg.src,
            ))

    @database_sync_to_async
    def log_received_message(self, msg: messages.Message) -> MeshNode:
        node, created = MeshNode.objects.get_or_create(address=msg.src)
        return NodeMessage.objects.create(
            node=node,
            message_type=msg.msg_id,
            data=msg.tojson()
        )
