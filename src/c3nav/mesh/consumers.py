import asyncio
import traceback
from asyncio import get_event_loop

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer, AsyncWebsocketConsumer
from django.db import transaction
from django.utils import timezone

from c3nav.mesh import messages
from c3nav.mesh.messages import (MESH_BROADCAST_ADDRESS, MESH_NONE_ADDRESS, MESH_ROOT_ADDRESS, MeshMessage,
                                 MeshMessageType)
from c3nav.mesh.models import MeshNode, MeshUplink, NodeMessage
from c3nav.mesh.utils import get_mesh_comm_group


class MeshConsumer(AsyncWebsocketConsumer):
    def __init__(self):
        super().__init__()
        self.uplink = None
        self.dst_nodes = set()
        self.open_requests = set()
        self.ping_task = None

    async def connect(self):
        # todo: auth

        await self.log_text(None, "new mesh websocket connection")
        await self.accept()
        self.ping_task = get_event_loop().create_task(self.ping_regularly())

    async def disconnect(self, close_code):
        self.ping_task.cancel()
        await self.log_text(self.uplink.node, "mesh websocket disconnected")
        if self.uplink is not None:
            # leave broadcast group
            await self.channel_layer.group_discard(
                get_mesh_comm_group(MESH_BROADCAST_ADDRESS), self.channel_name
            )

            # remove all other destinations
            await self.remove_dst_nodes(self.dst_nodes)

            # set end reason (unless we set it to replaced already)
            # todo: make this better? idk
            await MeshUplink.objects.filter(
                pk=self.uplink.pk,
            ).exclude(
                end_reason=MeshUplink.EndReason.REPLACED
            ).aupdate(
                end_reason=MeshUplink.EndReason.CLOSED
            )

    async def send_msg(self, msg, sender=None, exclude_uplink_address=None):
        # print("sending", msg, MeshMessage.encode(msg).hex(' ', 1))
        # self.log_text(msg.dst, "sending %s" % msg)
        await self.send(bytes_data=MeshMessage.encode(msg))
        await self.channel_layer.group_send("mesh_msg_sent", {
            "type": "mesh.msg_sent",
            "timestamp": timezone.now().strftime("%d.%m.%y %H:%M:%S.%f"),
            "channel": self.channel_name,
            "sender": sender,
            "uplink": self.uplink.node.address if self.uplink else None,
            "recipient": msg.dst,
            # "msg": msg.tojson(),  # not doing this part for privacy reasons
        })

    async def receive(self, text_data=None, bytes_data=None):
        if bytes_data is None:
            return
        try:
            msg, data = messages.MeshMessage.decode(bytes_data)
        except Exception:
            traceback.print_exc()
            return

        print(msg)

        if msg.dst != messages.MESH_ROOT_ADDRESS and msg.dst != messages.MESH_PARENT_ADDRESS:
            # message not adressed to us, forward it
            print('Received message for forwarding:', msg)

            if not self.uplink:
                await self.log_text(None, "received message not for us before sign in message, ignoring...")
                print('no sign in yet, ignoring')
                return

            # trace messages collect node adresses before forwarding
            if isinstance(msg, messages.MeshRouteTraceMessage):
                print('adding ourselves to trace message before forwarding')
                await self.log_text(MESH_ROOT_ADDRESS, "adding ourselves to trace message before forwarding")
                msg.trace.append(MESH_ROOT_ADDRESS)

            msg.send(exclude_uplink_address=self.uplink.node.address)

            # don't handle this message unless it's a broadcast message
            if msg.dst != messages.MESH_BROADCAST_ADDRESS:
                # don't handle this message unless it's a broadcast message
                await self.log_text(MESH_ROOT_ADDRESS, "received non-broadcast message not for us, forwarding...")
                return
            print('it\'s a broadcast so it\'s also for us')
            await self.log_text(MESH_ROOT_ADDRESS, "received broadcast message, forwarding and handling...")

        # print('Received message:', msg)

        src_node, created = await MeshNode.objects.aget_or_create(address=msg.src)

        if isinstance(msg, messages.MeshSigninMessage):
            await self.create_uplink_in_database(msg.src)

            # inform other uplinks to shut down
            await self.channel_layer.group_send(get_mesh_comm_group(msg.src), {
                "type": "mesh.uplink_consumer",
                "name": self.channel_name,
            })

            # log message, since we will not log it further down
            await self.log_received_message(src_node, msg)

            # inform signed in uplink node about its layer
            await self.send_msg(messages.MeshLayerAnnounceMessage(
                src=messages.MESH_ROOT_ADDRESS,
                dst=msg.src,
                layer=messages.NO_LAYER
            ))

            # add signed in uplink node to broadcast group
            await self.channel_layer.group_add(
                get_mesh_comm_group(MESH_BROADCAST_ADDRESS), self.channel_name
            )

            # add this node as a destination that this uplink handles (duh)
            await self.add_dst_nodes(nodes=(src_node, ))

            return

        if self.uplink is None:
            print('Expected sign-in message, but got a different one!')
            await self.close()
            return

        await self.log_received_message(src_node, msg)

        if isinstance(msg, messages.MeshAddDestinationsMessage):
            await self.add_dst_nodes(addresses=msg.addresses)

        if isinstance(msg, messages.MeshRemoveDestinationsMessage):
            await self.remove_dst_nodes(addresses=msg.addresses)

        if isinstance(msg, messages.MeshRouteRequestMessage):
            if msg.address == MESH_ROOT_ADDRESS:
                await self.log_text(MESH_ROOT_ADDRESS, "route request about us, start a trace")
                messages.MeshRouteTraceMessage(
                    src=MESH_ROOT_ADDRESS,
                    dst=msg.src,
                    request_id=msg.request_id,
                    trace=[MESH_ROOT_ADDRESS],
                ).send()
            else:
                # todo: find a way to send a "no route" message if there is no route
                await self.log_text(MESH_ROOT_ADDRESS, "requesting route response responsible uplink")
                self.open_requests.add(msg.request_id)
                await self.channel_layer.group_send(get_mesh_comm_group(msg.address), {
                    "type": "mesh.send_route_response",
                    "request_id": msg.request_id,
                    "channel": self.channel_name,
                    "dst": msg.src,
                })
                await self.delayed_group_send(5, self.channel_name, {
                    "type": "mesh.no_route_response",
                    "request_id": msg.request_id,
                    "dst": msg.src,
                })

    @database_sync_to_async
    def create_uplink_in_database(self, address):
        with transaction.atomic():
            # tatabase fumbling, lock the mesh node database row
            locked_node = MeshNode.objects.select_for_update().get(address=address)

            # close other uplinks in the database (they might add their own close reason in a bit)
            locked_node.uplink_sessions.filter(end_reason__isnull=True).update(
                end_reason=MeshUplink.EndReason.NEW_TIMEOUT
            )

            # create our own uplink in the database
            self.uplink = MeshUplink.objects.create(
                node=locked_node,
                last_ping=timezone.now(),
                name=self.channel_name,
            )

    async def ping_regularly(self):
        while True:
            await asyncio.sleep(5)
            await MeshUplink.objects.filter(pk=self.uplink.pk).aupdate(last_ping=timezone.now())

    async def delayed_group_send(self, delay: int, group: str, msg: dict):
        await asyncio.sleep(delay)
        await self.channel_layer.group_send(group, msg)

    """
    internal event handlers
    """

    async def mesh_uplink_consumer(self, data):
        """
        message handler: if we are not the given uplink, leave this group
        """
        if data["name"] != self.channel_name:
            await self.log_text(self.uplink.node, "shutting down, uplink now served by new consumer")
            await MeshUplink.objects.filter(pk=self.uplink.pk,).aupdate(
                end_reason=MeshUplink.EndReason.REPLACED
            )
            await self.close()

    async def mesh_dst_node_uplink(self, data):
        """
        message handler: if we are not the given uplink, leave this group
        """
        if data["uplink"] != self.uplink.node.address:
            await self.log_text(data["address"], "node now served by new consumer")
            await self.remove_dst_nodes((data["address"], ))

    async def mesh_send(self, data):
        if self.uplink.node.address == data["exclude_uplink_address"]:
            if data["msg"]["dst"] == MESH_BROADCAST_ADDRESS:
                await self.log_text(
                    self.uplink.node.address, "not forwarding this broadcast message via us since it came from here"
                )
            else:
                await self.log_text(
                    self.uplink.node.address, "we're the route for this message but it came from here so... no"
                )
            return
        await self.send_msg(MeshMessage.fromjson(data["msg"]), data["sender"])

    async def mesh_send_route_response(self, data):
        await self.log_text(self.uplink.node.address, "we're the uplink for this address, sending route response...")
        messages.MeshRouteResponseMessage(
            src=MESH_ROOT_ADDRESS,
            dst=data["dst"],
            request_id=data["request_id"],
            route=self.uplink.node.address,
        ).send()
        async_to_sync(self.channel_layer.send)(data["channel"], {
            "type": "mesh.route_response_sent",
            "request_id": data["request_id"],
        })

    async def mesh_route_response_sent(self, data):
        self.open_requests.discard(data["request_id"])

    async def mesh_no_route_response(self, data):
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

    """
    helper functions
    """

    async def log_received_message(self, src_node: MeshNode, msg: messages.MeshMessage):
        as_json = MeshMessage.tojson(msg)
        await self.channel_layer.group_send("mesh_msg_received", {
            "type": "mesh.msg_received",
            "timestamp": timezone.now().strftime("%d.%m.%y %H:%M:%S.%f"),
            "channel": self.channel_name,
            "uplink": self.uplink.node.address if self.uplink else None,
            "msg": as_json,
        })
        await NodeMessage.objects.acreate(
            uplink=self.uplink,
            src_node=src_node,
            message_type=msg.msg_type.name,
            data=as_json,
        )

    async def log_text(self, address, text):
        address = getattr(address, 'address', address)
        await self.channel_layer.group_send("mesh_log", {
            "type": "mesh.log_entry",
            "timestamp": timezone.now().strftime("%d.%m.%y %H:%M:%S.%f"),
            "channel": self.channel_name,
            "uplink": self.uplink.node.address if self.uplink else None,
            "node": address,
            "text": text,
        })
        print("MESH %s: [%s] %s" % (self.uplink.node, address, text))

    async def add_dst_nodes(self, nodes=None, addresses=None):
        nodes = list(nodes) if nodes else []
        addresses = set(addresses) if addresses else set()

        node_addresses = set(node.address for node in nodes)
        missing_addresses = addresses - set(node.address for node in nodes)

        if missing_addresses:
            await MeshNode.objects.abulk_create(
                [MeshNode(address=address) for address in missing_addresses],
                ignore_conflicts=True
            )

        addresses |= node_addresses
        addresses |= missing_addresses

        for address in addresses:
            await self.log_text(address, "destination added")

            # add ourselves as uplink
            await self._add_destination(address)

            # tell the node to dump its current information
            await self.send_msg(
                messages.ConfigDumpMessage(
                    src=messages.MESH_ROOT_ADDRESS,
                    dst=address,
                )
            )

    @database_sync_to_async
    def _add_destination(self, address):
        with transaction.atomic():
            node = MeshNode.objects.select_for_update().get(address=address)

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
                "uplink": self.uplink.node.address
            })

            node.uplink = self.uplink,
            node.last_signin = timezone.now()
            node.save()

    async def remove_dst_nodes(self, addresses):
        for address in tuple(addresses):
            await self.log_text(address, "destination removed")

            await self._remove_destination(address)

    @database_sync_to_async
    def _remove_destination(self, address):
        with transaction.atomic():
            node = MeshNode.objects.select_for_update().get(address=address)

            # create group name for this address
            group = get_mesh_comm_group(address)

            # leave the group
            if address in self.dst_nodes:
                async_to_sync(self.channel_layer.group_discard)(group, self.channel_name)
                self.dst_nodes.discard(address)

            node.uplink = None
            node.save()


class MeshUIConsumer(AsyncJsonWebsocketConsumer):
    def __init__(self):
        super().__init__()
        self.msg_sent_filter = {}
        self.msg_received_filter = {}

    async def connect(self):
        # todo: auth
        await self.accept()

    async def receive_json(self, content, **kwargs):
        if content.get("subscribe", None) == "log":
            await self.channel_layer.group_add("mesh_log", self.channel_name)
        if content.get("subscribe", None) == "msg_sent":
            await self.channel_layer.group_add("mesh_msg_sent", self.channel_name)
            self.msg_sent_filter = dict(content.get("filter", {}))
        if content.get("subscribe", None) == "msg_received":
            await self.channel_layer.group_add("mesh_msg_sent", self.channel_name)
            self.msg_received_filter = dict(content.get("filter", {}))
        if "send_msg" in content:
            msg_to_send = self.scope["session"].pop("mesh_msg_%s" % content["send_msg"], None)
            if not msg_to_send:
                return
            self.scope["session"].save()

            await self.channel_layer.group_add("mesh_msg_sent", self.channel_name)
            self.msg_sent_filter = {"sender": self.channel_name}

            if msg_to_send["msg_data"]["msg_type"] == MeshMessageType.MESH_ROUTE_REQUEST.name:
                await self.channel_layer.group_add("mesh_msg_received", self.channel_name)
                self.msg_received_filter = {"request_id": msg_to_send["msg_data"]["request_id"]}

            for recipient in msg_to_send["recipients"]:
                MeshMessage.fromjson({
                    'dst': recipient,
                    **msg_to_send["msg_data"],
                }).send(sender=self.channel_name)

    async def mesh_log_entry(self, data):
        await self.send_json(data)

    async def mesh_msg_sent(self, data):
        for key, value in self.msg_sent_filter.items():
            if isinstance(value, list):
                if data.get(key, None) not in value:
                    return
            else:
                if data.get(key, None) != value:
                    return
        await self.send_json(data)

    async def mesh_msg_received(self, data):
        for key, filter_value in self.msg_received_filter.items():
            value = data.get(key, data["msg"].get(key, None))
            if isinstance(filter_value, list):
                if value not in filter_value:
                    return
            else:
                if value != filter_value:
                    return
        await self.send_json(data)

    async def disconnect(self, code):
        await self.channel_layer.group_discard("mesh_log", self.channel_name)
        await self.channel_layer.group_discard("mesh_msg_sent", self.channel_name)
        await self.channel_layer.group_discard("mesh_msg_received", self.channel_name)
