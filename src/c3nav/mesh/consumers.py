import traceback

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from c3nav.mesh import messages
from c3nav.mesh.models import MeshNode, NodeMessage, Firmware


class MeshConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        print('connected!')
        # todo: auth
        self.node = None
        await self.accept()

    async def disconnect(self, close_code):
        print('disconnected!')
        if self.node is not None:
            await self.remove_route(self.node.address)
            await self.channel_layer.group_discard('route_%s' % self.node.address.replace(':', ''), self.channel_name)
        await self.channel_layer.group_discard('route_broadcast', self.channel_name)

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

        if isinstance(msg, messages.MeshSigninMessage):
            self.node, created = await self.get_node(msg.src)
            if created:
                print('New node signing in!')
                print(self.node)
            await self.log_received_message(msg)
            await self.send_msg(messages.MeshLayerAnnounceMessage(
                src=messages.ROOT_ADDRESS,
                dst=msg.src,
                layer=messages.NO_LAYER
            ))
            await self.send_msg(messages.ConfigDumpMessage(
                src=messages.ROOT_ADDRESS,
                dst=msg.src,
            ))
            await self.channel_layer.group_add('route_%s' % self.node.address.replace(':', ''), self.channel_name)
            await self.channel_layer.group_add('route_broadcast', self.channel_name)
            await self.set_parent_of_nodes(None, (self.node.address, ))
            await self.add_route_to_nodes(self.node.address, (self.node.address,))
            return

        if self.node is None:
            print('Expected sign-in message, but got a different one!')
            await self.close()
            return

        await self.log_received_message(msg)

        if isinstance(msg, messages.ConfigFirmwareMessage):
            await self._handle_config_firmware_msg(msg)
            return

    @database_sync_to_async
    def _handle_config_firmware_msg(self, msg):
        self.firmware, created = Firmware.objects.get_or_create(**msg.to_model_data())
        self.node.firmware = self.firmware
        self.node.save()

    @database_sync_to_async
    def get_node(self, address):
        return MeshNode.objects.get_or_create(address=address)

    @database_sync_to_async
    def log_received_message(self, msg: messages.Message):
        NodeMessage.objects.create(
            node=self.node,
            message_type=msg.msg_id,
            data=msg.tojson()
        )

    @database_sync_to_async
    def create_nodes(self, addresses):
        MeshNode.objects.bulk_create(MeshNode(address=address) for address in addresses)

    @database_sync_to_async
    def set_parent_of_nodes(self, parent_address, node_addresses):
        MeshNode.objects.filter(address__in=node_addresses).update(parent_node_id=parent_address)

    @database_sync_to_async
    def add_route_to_nodes(self, route_address, node_addresses):
        MeshNode.objects.filter(address__in=node_addresses).update(route_id=route_address)

    @database_sync_to_async
    def remove_route(self, route_address):
        MeshNode.objects.filter(route_id=route_address).update(route_id=None)

    @database_sync_to_async
    def remove_route_to_nodes(self, route_address, node_addresses):
        MeshNode.objects.filter(address__in=node_addresses, route_id=route_address).update(route_id=None)

    @database_sync_to_async
    def set_node_firmware(self, firmware):
        self.node.firmware = firmware
        self.node.save()