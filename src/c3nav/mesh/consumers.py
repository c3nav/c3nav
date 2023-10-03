import traceback

from asgiref.sync import async_to_sync
from channels.generic.websocket import WebsocketConsumer

from c3nav.mesh import messages
from c3nav.mesh.models import MeshNode, NodeMessage


# noinspection PyAttributeOutsideInit
class MeshConsumer(WebsocketConsumer):
    def connect(self):
        print('connected!')
        # todo: auth
        self.uplink_node = None
        self.dst_nodes = set()
        self.accept()

    def disconnect(self, close_code):
        print('disconnected!')
        if self.uplink_node is not None:
            self.remove_route(self.uplink_node)
            self.channel_layer.group_discard('route_%s' % self.node.address.replace(':', ''), self.channel_name)
        self.channel_layer.group_discard('route_broadcast', self.channel_name)

    def send_msg(self, msg):
        print('Sending message:', msg)
        self.send(bytes_data=msg.encode())

    def receive(self, text_data=None, bytes_data=None):
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

        src_node, created = MeshNode.objects.get_or_create(address=msg.src)

        if isinstance(msg, messages.MeshSigninMessage):
            self.uplink_node = src_node
            # log message, since we will not log it further down
            self.log_received_message(src_node, msg)

            # inform signed in uplink node about its layer
            self.send_msg(messages.MeshLayerAnnounceMessage(
                src=messages.ROOT_ADDRESS,
                dst=msg.src,
                layer=messages.NO_LAYER
            ))

            # add signed in uplink node to broadcast route
            async_to_sync(self.channel_layer.group_add)('mesh_broadcast', self.channel_name)

            # add this node as a destination that this uplink handles (duh)
            self.add_dst_nodes((src_node.address, ))

            return

        if self.uplink_node is None:
            print('Expected sign-in message, but got a different one!')
            self.close()
            return

        self.log_received_message(src_node, msg)

    def uplink_change(self, data):
        # message handler: if we are not the given uplink, leave this group
        if data["uplink"] != self.uplink_node.address:
            group = self.group_name_for_node(data["address"])
            print('leaving uplink group...')
            async_to_sync(self.channel_layer.group_discard)(group, self.channel_name)

    def log_received_message(self, src_node: MeshNode, msg: messages.Message):
        NodeMessage.objects.create(
            uplink_node=self.uplink_node,
            src_node=src_node,
            message_type=msg.msg_id,
            data=msg.tojson()
        )

    def add_dst_nodes(self, addresses):
        # add ourselves to this one
        for address in addresses:
            # create group name for this address
            group = self.group_name_for_node(address)

            # if we aren't handling this address yet, join the group
            if address not in self.dst_nodes:
                async_to_sync(self.channel_layer.group_add)(group, self.channel_name)
                self.dst_nodes.add(address)

            # tell other consumers to leave the group
            async_to_sync(self.channel_layer.group_send)(group, {
                "type": "uplink_change",
                "node": address,
                "uplink": self.uplink_node.address
            })

            # tell the node to dump its current information
            self.send_msg(
                messages.ConfigDumpMessage(
                    src=messages.ROOT_ADDRESS,
                    dst=address,
                )
            )

        # add the stuff to the db as well
        MeshNode.objects.filter(address__in=addresses).update(route_id=self.uplink_node.address)

    def group_name_for_node(self, address):
        return 'mesh_%s' % address.replace(':', '-')

    def remove_route(self, route_address):
        MeshNode.objects.filter(route_id=route_address).update(route_id=None)
