import traceback

from asgiref.sync import async_to_sync
from channels.generic.websocket import WebsocketConsumer, JsonWebsocketConsumer
from django.utils import timezone

from c3nav.mesh.utils import get_mesh_comm_group
from c3nav.mesh import messages
from c3nav.mesh.messages import MeshMessage, MESH_BROADCAST_ADDRESS, MeshMessageType, MESH_ROOT_ADDRESS, \
    MESH_NONE_ADDRESS
from c3nav.mesh.models import MeshNode, NodeMessage
from c3nav.mesh.tasks import send_channel_msg


# noinspection PyAttributeOutsideInit
class MeshConsumer(WebsocketConsumer):
    def connect(self):
        # todo: auth
        self.uplink_node = None
        self.log_text(None, "new mesh websocket connection")
        self.dst_nodes = set()
        self.open_requests = set()
        self.accept()

    def disconnect(self, close_code):
        self.log_text(self.uplink_node, "mesh websocket disconnected")
        if self.uplink_node is not None:
            # leave broadcast group
            async_to_sync(self.channel_layer.group_discard)(
                get_mesh_comm_group(MESH_BROADCAST_ADDRESS), self.channel_name
            )

            # remove all other destinations
            self.remove_dst_nodes(self.dst_nodes)

    def send_msg(self, msg, sender=None, exclude_uplink_address=None):
        #print("sending", msg, MeshMessage.encode(msg).hex(' ', 1))
        #self.log_text(msg.dst, "sending %s" % msg)
        self.send(bytes_data=MeshMessage.encode(msg))
        async_to_sync(self.channel_layer.group_send)("mesh_msg_sent", {
            "type": "mesh.msg_sent",
            "timestamp": timezone.now().strftime("%d.%m.%y %H:%M:%S.%f"),
            "channel": self.channel_name,
            "sender": sender,
            "uplink": self.uplink_node.address if self.uplink_node else None,
            "recipient": msg.dst,
            #"msg": msg.tojson(),  # not doing this part for privacy reasons
        })

    def receive(self, text_data=None, bytes_data=None):
        if bytes_data is None:
            return
        try:
            msg, data = messages.MeshMessage.decode(bytes_data)
        except Exception:
            traceback.print_exc()
            return

        if msg.dst != messages.MESH_ROOT_ADDRESS and msg.dst != messages.MESH_PARENT_ADDRESS:
            # message not adressed to us, forward it
            print('Received message for forwarding:', msg)

            if not self.uplink_node:
                self.log_text(self.uplink_node, "received message not for us before sign in message, ignoring...")
                print('no sign in yet, ignoring')
                return

            # trace messages collect node adresses before forwarding
            if isinstance(msg, messages.MeshRouteTraceMessage):
                print('adding ourselves to trace message before forwarding')
                self.log_text(MESH_ROOT_ADDRESS, "adding ourselves to trace message before forwarding")
                msg.trace.append(MESH_ROOT_ADDRESS)

            msg.send(exclude_uplink_address=self.uplink_node.address)

            # don't handle this message unless it's a broadcast message
            if msg.dst != messages.MESH_BROADCAST_ADDRESS:
                # don't handle this message unless it's a broadcast message
                self.log_text(MESH_ROOT_ADDRESS, "received non-broadcast message not for us, forwarding...")
                return
            print('it\'s a broadcast so it\'s also for us')
            self.log_text(MESH_ROOT_ADDRESS, "received broadcast message, forwarding and handling...")

        #print('Received message:', msg)

        src_node, created = MeshNode.objects.get_or_create(address=msg.src)

        if isinstance(msg, messages.MeshSigninMessage):
            self.uplink_node = src_node
            # log message, since we will not log it further down
            self.log_received_message(src_node, msg)

            # inform signed in uplink node about its layer
            self.send_msg(messages.MeshLayerAnnounceMessage(
                src=messages.MESH_ROOT_ADDRESS,
                dst=msg.src,
                layer=messages.NO_LAYER
            ))

            # add signed in uplink node to broadcast group
            async_to_sync(self.channel_layer.group_add)(
                get_mesh_comm_group(MESH_BROADCAST_ADDRESS), self.channel_name
            )

            # kick out other consumers talking to the same uplink
            async_to_sync(self.channel_layer.group_send)(get_mesh_comm_group(msg.src), {
                "type": "mesh.uplink_consumer",
                "name": self.channel_name,
            })

            # add this node as a destination that this uplink handles (duh)
            self.add_dst_nodes(nodes=(src_node, ))

            return

        if self.uplink_node is None:
            print('Expected sign-in message, but got a different one!')
            self.close()
            return

        self.log_received_message(src_node, msg)

        if isinstance(msg, messages.MeshAddDestinationsMessage):
            self.add_dst_nodes(addresses=msg.addresses)

        if isinstance(msg, messages.MeshRemoveDestinationsMessage):
            self.remove_dst_nodes(addresses=msg.addresses)

        if isinstance(msg, messages.MeshRouteRequestMessage):
            if msg.address == MESH_ROOT_ADDRESS:
                self.log_text(MESH_ROOT_ADDRESS, "route request about us, start a trace")
                messages.MeshRouteTraceMessage(
                    src=MESH_ROOT_ADDRESS,
                    dst=msg.src,
                    request_id=msg.request_id,
                    trace=[MESH_ROOT_ADDRESS],
                ).send()
            else:
                # todo: find a way to send a "no route" message if there is no route
                self.log_text(MESH_ROOT_ADDRESS, "requesting route response responsible uplink")
                self.open_requests.add(msg.request_id)
                async_to_sync(self.channel_layer.group_send)(get_mesh_comm_group(msg.address), {
                    "type": "mesh.send_route_response",
                    "request_id": msg.request_id,
                    "channel": self.channel_name,
                    "dst": msg.src,
                })
                send_channel_msg.apply_async(self.channel_name, {
                    "type": "mesh.no_route_response",
                    "request_id": msg.request_id,
                    "dst": msg.src,
                }, countdown=5)

    def mesh_uplink_consumer(self, data):
        # message handler: if we are not the given uplink, leave this group
        if data["name"] != self.channel_name:
            self.log_text(self.uplink_node, "shutting down, uplink now served by new consumer")
            self.close()

    def mesh_dst_node_uplink(self, data):
        # message handler: if we are not the given uplink, leave this group
        if data["uplink"] != self.uplink_node.address:
            self.log_text(data["address"], "node now served by new consumer")
            self.remove_dst_nodes((data["address"], ))

    def mesh_send(self, data):
        if self.uplink_node.address == data["exclude_uplink_address"]:
            if data["msg"]["dst"] == MESH_BROADCAST_ADDRESS:
                self.log_text(
                    self.uplink_node.address, "not forwarding this broadcast message via us since it came from here"
                )
            else:
                self.log_text(
                    self.uplink_node.address, "we're the route for this message but it came from here so... no"
                )
            return
        self.send_msg(MeshMessage.fromjson(data["msg"]), data["sender"])

    def mesh_send_route_response(self, data):
        self.log_text(self.uplink_node.address, "we're the uplink for this address, sending route response...")
        messages.MeshRouteResponseMessage(
            src=MESH_ROOT_ADDRESS,
            dst=data["dst"],
            request_id=data["request_id"],
            route=self.uplink_node.address,
        ).send()
        async_to_sync(self.channel_layer.send)(data["channel"], {
            "type": "mesh.route_response_sent",
            "request_id": data["request_id"],
        })

    def mesh_route_response_sent(self, data):
        self.open_requests.discard(data["request_id"])

    def mesh_no_route_response(self, data):
        print('no route response check')
        if data["request_id"] not in self.open_requests:
            print('a route was sent')
            return
        print('sending no route')
        messages.MeshRouteResponseMessage(
            src=MESH_ROOT_ADDRESS,
            dst=data["dst"],
            request_id=data["request_id"],
            route=MESH_NONE_ADDRESS,
        ).send()

    def log_received_message(self, src_node: MeshNode, msg: messages.MeshMessage):
        as_json = MeshMessage.tojson(msg)
        async_to_sync(self.channel_layer.group_send)("mesh_msg_received", {
            "type": "mesh.msg_received",
            "timestamp": timezone.now().strftime("%d.%m.%y %H:%M:%S.%f"),
            "channel": self.channel_name,
            "uplink": self.uplink_node.address if self.uplink_node else None,
            "msg": as_json,
        })
        NodeMessage.objects.create(
            uplink_node=self.uplink_node,
            src_node=src_node,
            message_type=msg.msg_id,
            data=as_json,
        )

    def log_text(self, address, text):
        address = getattr(address, 'address', address)
        async_to_sync(self.channel_layer.group_send)("mesh_log", {
            "type": "mesh.log_entry",
            "timestamp": timezone.now().strftime("%d.%m.%y %H:%M:%S.%f"),
            "channel": self.channel_name,
            "uplink": self.uplink_node.address if self.uplink_node else None,
            "node": address,
            "text": text,
        })
        print("MESH %s: [%s] %s" % (self.uplink_node, address, text))

    def add_dst_nodes(self, nodes=None, addresses=None):
        nodes = list(nodes) if nodes else []
        addresses = set(addresses) if addresses else set()

        node_addresses = set(node.address for node in nodes)
        missing_addresses = addresses - set(node.address for node in nodes)

        if missing_addresses:
            MeshNode.objects.bulk_create(
                [MeshNode(address=address) for address in missing_addresses],
                ignore_conflicts=True
            )

        addresses |= node_addresses
        addresses |= missing_addresses

        for address in addresses:
            self.log_text(address, "destination added")

            # create group name for this address
            group = get_mesh_comm_group(address)

            # if we aren't handling this address yet, join the group
            if address not in self.dst_nodes:
                async_to_sync(self.channel_layer.group_add)(group, self.channel_name)
                self.dst_nodes.add(address)

            # tell other consumers to leave the group
            async_to_sync(self.channel_layer.group_send)(group, {
                "type": "mesh.dst_node_uplink",
                "node": address,
                "uplink": self.uplink_node.address
            })

            # tell the node to dump its current information
            self.send_msg(
                messages.ConfigDumpMessage(
                    src=messages.MESH_ROOT_ADDRESS,
                    dst=address,
                )
            )

        # add the stuff to the db as well
        MeshNode.objects.filter(address__in=addresses).update(
            uplink_id=self.uplink_node.address,
            last_signin=timezone.now(),
        )

    def remove_dst_nodes(self, addresses):
        for address in tuple(addresses):
            self.log_text(address, "destination removed")

            # create group name for this address
            group = get_mesh_comm_group(address)

            # leave the group
            if address in self.dst_nodes:
                async_to_sync(self.channel_layer.group_discard)(group, self.channel_name)
                self.dst_nodes.discard(address)

        # add the stuff to the db as well
        # todo: shouldn't do this because of race condition?
        MeshNode.objects.filter(address__in=addresses, uplink_id=self.uplink_node.address).update(
            uplink_id=None,
        )


class MeshUIConsumer(JsonWebsocketConsumer):
    def connect(self):
        # todo: auth
        self.accept()
        self.msg_sent_filter = {}
        self.msg_received_filter = {}

    def receive_json(self, content, **kwargs):
        if content.get("subscribe", None) == "log":
            async_to_sync(self.channel_layer.group_add)("mesh_log", self.channel_name)
        if content.get("subscribe", None) == "msg_sent":
            async_to_sync(self.channel_layer.group_add)("mesh_msg_sent", self.channel_name)
            self.msg_sent_filter = dict(content.get("filter", {}))
        if content.get("subscribe", None) == "msg_received":
            async_to_sync(self.channel_layer.group_add)("mesh_msg_sent", self.channel_name)
            self.msg_received_filter = dict(content.get("filter", {}))
        if "send_msg" in content:
            msg_to_send = self.scope["session"].pop("mesh_msg_%s" % content["send_msg"], None)
            if not msg_to_send:
                return
            self.scope["session"].save()

            async_to_sync(self.channel_layer.group_add)("mesh_msg_sent", self.channel_name)
            self.msg_sent_filter = {"sender": self.channel_name}

            if msg_to_send["msg_data"]["msg_id"] == MeshMessageType.MESH_ROUTE_REQUEST:
                async_to_sync(self.channel_layer.group_add)("mesh_msg_received", self.channel_name)
                self.msg_received_filter = {"request_id": msg_to_send["msg_data"]["request_id"]}

            for recipient in msg_to_send["recipients"]:
                MeshMessage.fromjson({
                    'dst': recipient,
                    **msg_to_send["msg_data"],
                }).send(sender=self.channel_name)

    def mesh_log_entry(self, data):
        self.send_json(data)

    def mesh_msg_sent(self, data):
        for key, value in self.msg_sent_filter.items():
            if isinstance(value, list):
                if data.get(key, None) not in value:
                    return
            else:
                if data.get(key, None) != value:
                    return
        self.send_json(data)

    def mesh_msg_received(self, data):
        for key, filter_value in self.msg_received_filter.items():
            value = data.get(key, data["msg"].get(key, None))
            if isinstance(filter_value, list):
                if value not in filter_value:
                    return
            else:
                if value != filter_value:
                    return
        self.send_json(data)

    def disconnect(self, code):
        async_to_sync(self.channel_layer.group_discard)("mesh_log", self.channel_name)
        async_to_sync(self.channel_layer.group_discard)("mesh_msg_sent", self.channel_name)
        async_to_sync(self.channel_layer.group_discard)("mesh_msg_received", self.channel_name)
