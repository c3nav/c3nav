import asyncio
import traceback
from asyncio import get_event_loop
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum, auto, unique
from functools import cached_property
from typing import Optional

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.exceptions import DenyConnection
from channels.generic.websocket import AsyncJsonWebsocketConsumer, AsyncWebsocketConsumer
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from pydantic_extra_types.mac_address import MacAddress

from c3nav.mesh import messages
from c3nav.mesh.cformats import CFormat
from c3nav.mesh.messages import (MESH_BROADCAST_ADDRESS, MESH_NONE_ADDRESS, MESH_ROOT_ADDRESS, OTA_CHUNK_SIZE,
                                 MeshMessage, MeshMessageType, OTAApplyMessage, OTASettingMessage)
from c3nav.mesh.models import MeshNode, MeshUplink, NodeMessage, OTARecipientStatus, OTAUpdate, OTAUpdateRecipient
from c3nav.mesh.utils import MESH_ALL_OTA_GROUP, MESH_ALL_UPLINKS_GROUP, UPLINK_PING, get_mesh_uplink_group
from c3nav.routing.locator import Locator


class Unknown:
    pass


@unique
class NodeWaitingFor(IntEnum):
    NOTHING = auto()
    CONFIG = auto()
    OTA_START_STOP = auto()


@dataclass
class NodeState:
    waiting_for: NodeWaitingFor = NodeWaitingFor.CONFIG
    attempt: int = 0
    last_msg: dict[MeshMessageType: MeshMessage] = field(default_factory=dict)
    last_sent: datetime = field(default_factory=timezone.now)
    reported_ota_update: Optional[int] = None  # None = unknown, 0 = no update
    ota_recipient: Optional[OTAUpdateRecipient] = None


node_assignments = {'54:32:04:b6:fc:cd': (1, 'Alpheratz'),
 '54:32:04:b7:e2:35': (2, 'Ankaa'),
 '54:32:04:b7:8a:4d': (3, 'Schedar'),
 '54:32:04:b5:29:21': (4, 'Diphda'),
 '54:32:04:b8:51:05': (5, 'Achernar'),
 '54:32:04:b8:b8:05': (6, 'Hamal'),
 '54:32:04:b7:40:01': (7, 'Acamar'),
 '54:32:04:b6:ec:fd': (8, 'Menkar'),
 '54:32:04:b5:e6:f5': (9, 'Mirfak'),
 '54:32:04:b7:47:d9': (10, 'Aldebaran'),
 '54:32:04:b7:7c:f1': (11, 'Rigel'),
 '54:32:04:b5:d3:d1': (12, 'Capella'),
 '54:32:04:b6:17:f1': (13, 'Bellatrix'),
 '30:30:f9:c3:70:15': (14, 'Elnath'),
 '54:32:04:b5:2e:31': (15, 'Alnilam'),
 '54:32:04:b5:c4:d5': (16, 'Betelgeuse'),
 '54:32:04:b7:72:39': (17, 'Canopus'),
 '54:32:04:b7:75:05': (18, 'Sirius'),
 '54:32:04:b7:3d:59': (19, 'Adhara'),
 '54:32:04:b8:ac:31': (20, 'Procyon'),
 '54:32:04:b7:46:89': (21, 'Pollux'),
 '54:32:04:b7:83:e5': (22, 'Avior'),
 '54:32:04:b7:1b:ed': (23, 'Suhail'),
 '54:32:04:b7:84:99': (24, 'Miaplacidus'),
 '54:32:04:b6:cf:c1': (25, 'Alphard'),
 '48:31:b7:aa:57:c9': (26, 'Regulus'),
 '54:32:04:b7:cb:f5': (27, 'Dubhe'),
 '54:32:04:b5:67:b1': (28, 'Denebola'),
 '48:31:b7:ac:ad:71': (29, 'Gienah'),
 '54:32:04:b6:9a:71': (30, 'Acrux'),
 '54:32:04:b7:61:95': (31, 'Gacrux'),
 '54:32:04:b8:6f:49': (32, 'Alioth'),
 '30:30:f9:c3:9c:f9': (33, 'Spica'),
 '48:31:b7:ac:c7:f1': (34, 'Alkaid'),
 '54:32:04:b5:5f:8d': (35, 'Hadar'),
 '54:32:04:b7:1c:61': (36, 'Menkent'),
 '54:32:04:b8:78:69': (37, 'Arcturus'),
 '48:31:b7:ac:a6:89': (38, 'Rigil Kentaurus'),
 '54:32:04:b7:3e:89': (39, 'Zubenelgenubi'),
 '48:31:b7:aa:34:05': (40, 'Kochab'),
 '54:32:04:b7:0d:b9': (41, 'Alphecca'),
 '54:32:04:b5:a3:7d': (42, 'Antares'),
 '54:32:04:b7:f7:39': (43, 'Atria'),
 '54:32:04:b5:a9:79': (44, 'Sabik'),
 '54:32:04:b7:25:49': (45, 'Shaula'),
 '54:32:04:b7:3d:f9': (46, 'Rasalgethi'),
 '54:32:04:b6:fc:c5': (47, 'Eltanin'),
 '48:31:b7:aa:1a:25': (48, 'Kaus Australis'),
 '48:31:b7:aa:49:85': (49, 'Vega'),
 '48:31:b7:aa:66:01': (50, 'Nunki'),
 '48:31:b7:aa:36:7d': (51, 'Altair'),
 '48:31:b7:aa:3e:01': (52, 'Peacock'),
 '54:32:04:b6:ef:4d': (53, 'Deneb'),
 '54:32:04:b5:cc:a1': (54, 'Enif'),
 '48:31:b7:aa:b4:35': (55, 'Alnair'),
 '48:31:b7:ac:8a:a5': (56, 'Fomalhaut'),
 '48:31:b7:ab:98:6d': (57, 'Markab'),
 '54:32:04:b6:e9:e1': (58, 'Mimosa'),
 '54:32:04:b6:fe:01': (59, 'Toliman'),
 '54:32:04:b7:4b:2d': (60, 'Alnitak'),
 '48:31:b7:ac:2d:9d': (61, 'Wezen'),
 '48:31:b7:ab:d9:3d': (62, 'Sargas'),
 '48:31:b7:aa:24:81': (63, 'Menkalinan'),
 '54:32:04:b5:95:4d': (65, 'Polaris'),
 '54:32:04:b5:30:7d': (66, 'Castor'),
 '54:32:04:b7:db:ed': (67, 'Mirzam'),
 '48:31:b7:ac:c2:d1': (68, 'Alsephina'),
 '48:31:b7:aa:21:45': (69, 'Saiph'),
 '48:31:b7:ac:c1:7d': (70, 'Rasalhague'),
 '48:31:b7:aa:1a:7d': (71, 'Algol'),
 '30:30:f9:c3:7c:dd': (72, 'Almach'),
 '54:32:04:b6:19:25': (73, 'Tiaki'),
 '48:31:b7:aa:c4:45': (74, 'Aspidiske'),
 '48:31:b7:ac:35:05': (75, 'Naos'),
 '30:30:f9:c3:7c:d1': (76, 'Mizar'),
 '54:32:04:b7:04:41': (77, 'Sadr'),
 '54:32:04:b5:c3:19': (78, 'Mintaka'),
 '54:32:04:b5:66:19': (79, 'Caph'),
 '48:31:b7:ac:a4:11': (80, 'Dschubba'),
 '54:32:04:b5:31:fd': (81, 'Larawag'),
 '54:32:04:b8:1f:d9': (82, 'Merak'),
 '30:30:f9:c3:82:0d': (83, 'Izar'),
 '54:32:04:b5:b0:79': (84, 'Phecda'),
 '54:32:04:b6:fb:8d': (85, 'Scheat'),
 '54:32:04:b8:b5:61': (86, 'Alderamin'),
 '54:32:04:b7:3b:a9': (87, 'Aludra'),
 '54:32:04:b6:df:41': (88, 'Acrab'),
 '54:32:04:b7:d0:05': (89, 'Markeb'),
 '54:32:04:b7:cc:65': (90, 'Zosma'),
 '54:32:04:b7:4e:25': (91, 'Arneb'),
 '54:32:04:b8:8c:29': (92, 'Ascella'),
 '54:32:04:b7:3d:25': (93, 'Algieba'),
 '54:32:04:b8:72:29': (94, 'Zubeneschamali'),
 '54:32:04:b8:8a:a5': (95, 'Unukalhai'),
 '54:32:04:b8:b8:7d': (96, 'Sheratan'),
 '54:32:04:b8:aa:95': (97, 'Kraz'),
 '54:32:04:b5:4e:99': (98, 'Mahasim'),
 '54:32:04:b7:86:05': (99, 'Phact'),
 '54:32:04:b7:8b:d5': (100, 'Ruchbah')}



class MeshConsumer(AsyncWebsocketConsumer):
    mesh_msg_format = CFormat.from_annotation(MeshMessage)
    def __init__(self):
        super().__init__()
        self.uplink = None
        self.dst_nodes: dict[str, NodeState] = {}  # keys are addresses
        self.open_requests = set()
        self.ping_task = None
        self.check_node_state_task = None
        self.ota_send_task = None
        self.ota_chunks: dict[int, set[int]] = {}  # keys are update IDs, values are a list of chunk IDs
        self.ota_chunks_available_condition = asyncio.Condition()
        self.accepted = None

    async def connect(self):
        self.headers = dict(self.scope["headers"])
        if not constant_time_compare(self.headers[b"x-mesh-secret"].strip(),
                                     settings.SECRET_MESH_KEY.encode()):
            print("denying websocket connection with wrong mesh key")
            raise DenyConnection

        # await self.log_text(None, "new mesh websocket connection")
        await self.accept()
        self.ping_task = get_event_loop().create_task(self.ping_regularly())
        self.check_node_state_task = get_event_loop().create_task(self.check_node_states())
        self.ota_send_task = get_event_loop().create_task(self.ota_send())
        self.accepted = True

    async def disconnect(self, close_code):
        if not self.accepted:
            return
        self.ping_task.cancel()
        self.check_node_state_task.cancel()
        self.ota_send_task.cancel()
        if self.uplink is not None:
            await self.log_text(self.uplink.node, "mesh websocket disconnected")
            # leave broadcast group
            await self.channel_layer.group_discard("mesh_comm_broadcast", self.channel_name)

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

    async def send_msg(self, msg: MeshMessage, sender=None, exclude_uplink_address=None):
        # print("sending", msg, MeshMessage.encode(msg).hex(' ', 1))
        # self.log_text(msg_envelope.dst, "sending %s" % msg)
        await self.send(bytes_data=self.mesh_msg_format.encode(msg))
        await self.channel_layer.group_send("mesh_msg_sent", {
            "type": "mesh.msg_sent",
            "timestamp": timezone.now().strftime("%d.%m.%y %H:%M:%S.%f"),
            "channel": self.channel_name,
            "sender": sender,
            "uplink": self.uplink.node.address if self.uplink else None,
            "recipient": msg.dst,
            # "msg": msg.tojson(),  # not doing this part for privacy reasons
        })

    @cached_property
    def same_uplinks_group(self):
        return 'mesh_uplink_%s' % self.uplink.node.address.replace(':', '-')

    async def receive(self, text_data=None, bytes_data=None):
        if bytes_data is None:
            return
        try:
            msg, data = self.mesh_msg_format.decode(bytes_data)
            msg: MeshMessage
        except Exception:
            print("Unable to decode: msg_type=", hex(bytes_data[12]))
            print(bytes_data)
            traceback.print_exc()
            return
        msg.content = msg.content

        # print(msg)

        if msg.dst != messages.MESH_ROOT_ADDRESS and msg.dst != messages.MESH_PARENT_ADDRESS:
            # message not adressed to us, forward it
            print('Received message for forwarding:', msg.content)

            if not self.uplink:
                await self.log_text(None, "received message not for us before sign in message, ignoring...")
                print('no sign in yet, ignoring')
                return

            # trace messages collect node adresses before forwarding
            if isinstance(msg.content, messages.MeshRouteTraceMessage):
                print('adding ourselves to trace message before forwarding')
                await self.log_text(MESH_ROOT_ADDRESS, "adding ourselves to trace message before forwarding")
                msg.content.trace.append(MESH_ROOT_ADDRESS)

            result = await msg.content.send(exclude_uplink_address=self.uplink.node.address)

            if not result:
                print('message had no route')

            # don't handle this message unless it's a broadcast message
            if msg.dst != messages.MESH_BROADCAST_ADDRESS:
                # don't handle this message unless it's a broadcast message
                await self.log_text(MESH_ROOT_ADDRESS, "received non-broadcast message not for us, forwarding...")
                return
            print('it\'s a broadcast so it\'s also for us')
            await self.log_text(MESH_ROOT_ADDRESS, "received broadcast message, forwarding and handling...")

        # print('Received message:', msg)

        src_node, created = await MeshNode.objects.aget_or_create(address=msg.src)

        if isinstance(msg.content, messages.MeshSigninMessage):
            if not self.check_valid_address(msg.src):
                print('reject node with invalid address address')
                await self.close()
                return

            await self.create_uplink_in_database(msg.src)

            # inform other uplinks to shut down
            await self.channel_layer.group_send(get_mesh_uplink_group(msg.src), {
                "type": "mesh.uplink_consumer",
                "name": self.channel_name,
            })

            # log message, since we will not log it further down
            await self.log_received_message(src_node, msg)

            # inform signed in uplink node about its layer
            await self.send_msg(messages.MeshMessage(
                src=messages.MESH_ROOT_ADDRESS,
                dst=msg.src,
                content=messages.MeshLayerAnnounceMessage(
                    layer=messages.NO_LAYER
                )
            ))

            # add signed in uplink node to broadcast group
            await self.channel_layer.group_add(MESH_ALL_UPLINKS_GROUP, self.channel_name)

            # OTA releases bluh bluh
            await self.channel_layer.group_add(MESH_ALL_OTA_GROUP, self.channel_name)

            # add this node as a destination that this uplink handles (duh)
            await self.add_dst_node(src_node, parent_address=None)
            self.dst_nodes[msg.src].last_msg[MeshMessageType.MESH_SIGNIN] = msg.content

            return

        if self.uplink is None:
            print('Expected sign-in message, but got a different one!')
            await self.close()
            return

        await self.log_received_message(src_node, msg)

        try:
            node_status = self.dst_nodes[msg.src]
        except KeyError:
            print('unexpected message from', msg.src)
            return
        node_status.last_msg[msg.content.msg_type] = msg.content

        if isinstance(msg.content, messages.MeshAddDestinationMessage):
            try:
                node_status = self.dst_nodes[msg.content.via]
            except KeyError:
                print('unexpected AddDestinations message with via not served by us:', msg.content.via)
                await self.close()

            await self.add_dst_node(
                node=(await MeshNode.objects.aget_or_create(address=msg.content.destination))
                parent_address=msg.content.via,
            )
            await self.send_msg(messages.MeshMessage(
                src=MESH_ROOT_ADDRESS,
                dst=msg.content.via,
                content=messages.MeshSigninConfirmMessage(
                    address=msg.content.destination
                )
            ))

        if isinstance(msg.content, messages.MeshRemoveDestinationsMessage):
            await self.remove_dst_nodes(addresses=msg.content.addresses)

        if isinstance(msg.content, messages.MeshRouteRequestMessage):
            if msg.content.address == MESH_ROOT_ADDRESS:
                await self.log_text(MESH_ROOT_ADDRESS, "route request about us, start a trace")
                await self.send_msg(messages.MeshMessage(
                    src=MESH_ROOT_ADDRESS,
                    dst=msg.src,
                    content=messages.MeshRouteTraceMessage(
                        request_id=msg.content.request_id,
                        trace=[MESH_ROOT_ADDRESS],
                    )
                ))
            else:
                await self.log_text(MESH_ROOT_ADDRESS, "route request about someone else, sending response")
                self.open_requests.add(msg.content.request_id)
                uplink = database_sync_to_async(MeshNode.get_node_and_uplink)(msg.content.address)
                await self.send_msg(messages.MeshMessage(
                    src=MESH_ROOT_ADDRESS,
                    dst=msg.src,
                    content=messages.MeshRouteResponseMessage(
                        request_id=msg.content.request_id,
                        route=uplink.node_id if uplink else MESH_NONE_ADDRESS,
                    )
                ))

        if isinstance(msg.content, (messages.ConfigHardwareMessage,
                            messages.ConfigFirmwareMessage,
                            messages.ConfigBoardMessage)):
            if (node_status.waiting_for == NodeWaitingFor.CONFIG and
                    not {MeshMessageType.CONFIG_HARDWARE,
                         MeshMessageType.CONFIG_FIRMWARE,
                         MeshMessageType.CONFIG_BOARD} - set(node_status.last_msg.keys())):
                print('got all config, checking ota')
                await self.check_ota([msg.src], first_time=True)

        if isinstance(msg.content, messages.OTAStatusMessage):
            print('got OTA status', msg.content)
            node_status.reported_ota_update = msg.content.update_id
            if node_status.waiting_for == NodeWaitingFor.OTA_START_STOP:
                update_id = node_status.ota_recipient.update_id if node_status.ota_recipient else 0
                if update_id == msg.content.update_id:
                    print('start/cancel confirmed!')
                    node_status.waiting_for = NodeWaitingFor.NOTHING
                    if update_id:
                        if msg.content.status.is_failed:
                            print('ota failed')
                            node_status.ota_recipient.status = OTARecipientStatus.FAILED
                            await node_status.ota_recipient.send_status()
                            await OTAUpdateRecipient.objects.filter(pk=node_status.ota_recipient.pk).aupdate(
                                status=OTARecipientStatus.FAILED
                            )
                            node_status.ota_recipient = None
                        else:
                            print('queue chunk sending')
                            await self.ota_set_chunks(node_status.ota_recipient.update,
                                                      min_chunk=msg.content.next_expected_chunk)

        if isinstance(msg.content, messages.OTARequestFragmentsMessage):
            print('got OTA fragment request', msg.content)
            desired_update_id = node_status.ota_recipient.update_id if node_status.ota_recipient else 0
            if desired_update_id and msg.content.update_id == desired_update_id:
                print('queue requested chunk sending')
                await self.ota_set_chunks(node_status.ota_recipient.update, chunks=set(msg.content.chunks))

        if isinstance(msg.content, messages.ConfigNodeMessage):
            # todo: this could be nice if it was configurable
            if msg.content.number == 0:
                node_assignment = node_assignments.get(msg.src)
                if node_assignment:
                    number, name = node_assignment
                    await self.send_msg(messages.MeshMessage(
                        src=MESH_ROOT_ADDRESS,
                        dst=msg.src,
                        content=messages.ConfigNodeMessage(
                            number=number,
                            name=name,
                        )
                    ))
            else:
                await self.send_msg(messages.MeshMessage(
                    src=MESH_ROOT_ADDRESS,
                    dst=msg.src,
                    content=messages.ConfigIBeaconMessage(
                        uuid="a142621a-2f42-09b3-245b-e1ac6356e9b0",
                        major=1337,
                        minor=msg.content.number,
                    )
                ))


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
            await asyncio.sleep(UPLINK_PING)
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
        if data["uplink"] != self.channel_name:
            await self.log_text(data["node"], "node now served by new consumer")
            # going the short way cause the other consumer will already have done database stuff
            self.dst_nodes.pop(data["node"], None)

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
        await self.send_msg(MeshMessage.model_validate(data["msg"]), data["sender"])

    async def mesh_ota_recipients_changed(self, data):
        addresses = set(data["addresses"]) & set(self.dst_nodes.keys())
        print('recipients changed!')
        if not addresses:
            print('but none of ours')
            return
        await self.check_ota(addresses)

    """
    helper functions
    """

    async def log_received_message(self, src_node: MeshNode, msg: messages.MeshMessage):
        as_json = msg.model_dump(mode="json")
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
            message_type=msg.content.msg_type.name,
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
        print("MESH %s: [%s] %s" % (self.uplink.node.address, address, text))

    """ connection state machine """

    async def check_ota(self, addresses, first_time: bool = False):
        """
        this method will check the latest OTA for these nodes in the database

        it will ignore nodes that are still waiting for their config, unless first_time is set
        """
        recipients = await self.get_nodes_with_ota(addresses)
        for address, recipient in recipients.items():
            node_state = self.dst_nodes[address]
            if not first_time and node_state.waiting_for == NodeWaitingFor.CONFIG:
                # too soon
                continue

            # check if the installed firmware is the one we want to install
            if recipient:
                target_app_desc = recipient.update.build.firmware_image.app_desc
                fw_msg = node_state.last_msg.get(MeshMessageType.CONFIG_FIRMWARE, None)
                current_app_desc = fw_msg.app_desc if fw_msg else None
                print('target app desc:', target_app_desc)
                print('current app desc:', current_app_desc)
                if target_app_desc == current_app_desc:
                    print('the node already has this firmware, awesome')
                    recipient.status = OTARecipientStatus.SUCCESS
                    await recipient.send_status()
                    await OTAUpdateRecipient.objects.filter(pk=recipient.pk).aupdate(
                        status=OTARecipientStatus.SUCCESS
                    )
                    recipient = None
                else:
                    print('app desc does not match')

            desired_update_id = recipient.update_id if recipient else 0
            if desired_update_id != node_state.reported_ota_update:
                print('changing OTA state on node')
                node_state.waiting_for = NodeWaitingFor.OTA_START_STOP
                node_state.attempt = 0
                node_state.ota_recipient = recipient
                await self.node_resend_ask(address)
            else:
                node_state.ota_recipient = None

    @database_sync_to_async
    def get_nodes_with_ota(self, addresses) -> dict[str, Optional[OTAUpdateRecipient]]:
        return {node.address: node.current_ota
                for node in MeshNode.objects.prefetch_ota().filter(address__in=addresses)}

    async def node_resend_ask(self, address):
        node_state = self.dst_nodes[address]

        match(node_state.waiting_for):
            case NodeWaitingFor.NOTHING:
                return

            case NodeWaitingFor.CONFIG:
                node_state.last_sent = timezone.now()
                print('request config dump, attempt #%d' % node_state.attempt)
                node_state.attempt += 1
                await self.send_msg(messages.MeshMessage(
                    src=MESH_ROOT_ADDRESS,
                    dst=address,
                    content=messages.ConfigDumpMessage()
                ))

            case NodeWaitingFor.OTA_START_STOP:
                node_state.last_sent = timezone.now()
                if node_state.ota_recipient:
                    print('starting ota, attempt #%d' % node_state.attempt)
                    await self.send_msg(messages.MeshMessage(
                        src=MESH_ROOT_ADDRESS,
                        dst=address,
                        content=messages.OTAStartMessage(
                            update_id=node_state.ota_recipient.update_id,  # noqa
                            total_bytes=node_state.ota_recipient.update.build.binary.size,
                            auto_apply=False,
                            auto_reboot=False,
                        )
                    ))
                else:
                    print('canceling ota, attempt #%d' % node_state.attempt)
                    await self.send_msg(messages.MeshMessage(
                        src=MESH_ROOT_ADDRESS,
                        dst=address,
                        content=messages.OTAAbortMessage(
                            update_id=0,
                        )
                    ))

    async def check_node_states(self):
        while True:
            for address in tuple(self.dst_nodes.keys()):
                try:
                    if address not in self.dst_nodes:
                        self.dst_nodes.pop(address, None)
                        continue
                    node_state = self.dst_nodes.get(address, None)
                    if node_state:
                        if (node_state.waiting_for != NodeWaitingFor.NOTHING and
                                node_state.last_sent+timedelta(seconds=10) < timezone.now()):
                            await self.node_resend_ask(address)
                except Exception:  # noqa
                    print('failure in check_node_states')
                    traceback.print_exc()
            await asyncio.sleep(1)

    async def ota_set_chunks(self, update: OTAUpdate, chunks: Optional[set[int]] = None, min_chunk: int = 0):
        async with self.ota_chunks_available_condition:
            num_chunks = (update.build.binary.size-1)//OTA_CHUNK_SIZE+1
            print('queueing chunks for update', update.id, 'num_chunks=%d' % num_chunks, "chunks:", chunks)
            chunks = (set(range(min_chunk, num_chunks))
                      if chunks is None
                      else {chunk for chunk in chunks if chunk < num_chunks})
            self.ota_chunks.setdefault(update.id, set()).update(chunks)
            self.ota_chunks_available_condition.notify_all()

    async def ota_send(self):
        while True:
            for update_id in tuple(self.ota_chunks.keys()):
                try:
                    chunk = self.ota_chunks[update_id].pop()
                except KeyError:
                    # no longer there, go on
                    print('nothing left to send for update', update_id)
                    self.ota_chunks.pop(update_id, None)
                    continue

                # find recipients, so we know if broadcast or not
                recipients = [address for address, state in self.dst_nodes.items()
                              if state.ota_recipient and state.ota_recipient.update_id == update_id]
                if not recipients:
                    # no recipients? then lets stop
                    print('no more recipients for', update_id, 'stopping sending…')
                    self.ota_chunks.pop(update_id, None)
                    continue

                # send the message
                with self.dst_nodes[recipients[0]].ota_recipient.update.build.binary.open('rb') as f:
                    f.seek(chunk * OTA_CHUNK_SIZE)
                    data = f.read(OTA_CHUNK_SIZE)
                await self.send_msg(messages.MeshMessage(
                    src=MESH_ROOT_ADDRESS,
                    dst=recipients[0] if len(recipients) == 1 else MESH_BROADCAST_ADDRESS,
                    content=messages.OTAFragmentMessage(
                        update_id=update_id,
                        chunk=chunk,
                        data=data,
                    )
                ))

                # wait a bit until we send more
                await asyncio.sleep(0.1)  # 100ms, todo: 50ms would be nice but the chip can't take it right now

            async with self.ota_chunks_available_condition:
                if not self.ota_chunks:
                    await self.ota_chunks_available_condition.wait()

    """ routing """

    @staticmethod
    def check_valid_address(address):
        return not (address.startswith('00:00:00') or address.startswith('ff:ff:ff'))

    async def add_dst_node(self, node: MeshNode, parent_address: MacAddress | None):
        await self.log_text(node.address, "destination added")

        # add ourselves as uplink
        await self._add_destination(node.address, parent_address)

        # if we aren't handling this address yet, write it down
        if node.address not in self.dst_nodes:
            self.dst_nodes[node.address] = NodeState()

        await self.node_resend_ask(node.address)

    @database_sync_to_async
    def _add_destination(self, address, parent_address: MacAddress | None):
        with transaction.atomic():
            node = MeshNode.objects.select_for_update().get(address=address)
            # update database
            node.uplink = self.uplink
            node.upstream_id = parent_address
            node.last_signin = timezone.now()
            node.save()

            # tell other consumers that it's us now
            async_to_sync(self.channel_layer.group_send)(MESH_ALL_UPLINKS_GROUP, {
                "type": "mesh.dst_node_uplink",
                "node": address,
                "uplink": self.channel_name
            })

    async def remove_dst_nodes(self, addresses):
        for address in tuple(addresses):
            await self.log_text(address, "destination removed")
            await self._remove_destination(address)

    @database_sync_to_async
    def _remove_destination(self, address):
        with transaction.atomic():
            try:
                node = MeshNode.objects.select_for_update().get(address=address, uplink=self.uplink)
            except MeshNode.DoesNotExist:
                pass
            else:
                node.uplink = None
                node.save()

            # no longer serving this node
            if address in self.dst_nodes:
                self.dst_nodes.pop(address, None)


class MeshUIConsumer(AsyncJsonWebsocketConsumer):
    def __init__(self):
        super().__init__()
        self.msg_sent_filter = {}
        self.msg_received_filter = {}

    async def connect(self):
        if not self.scope["user_permissions"].mesh_control:
            raise DenyConnection
        await self.accept()

    async def receive_json(self, content, **kwargs):
        if content.get("subscribe", None) == "log":
            await self.channel_layer.group_add("mesh_log", self.channel_name)
        # disabled because security
        # if content.get("subscribe", None) == "msg_sent":
        #     await self.channel_layer.group_add("mesh_msg_sent", self.channel_name)
        #     self.msg_sent_filter = dict(content.get("filter", {}))
        # if content.get("subscribe", None) == "msg_received":
        #     await self.channel_layer.group_add("mesh_msg_sent", self.channel_name)
        #     self.msg_received_filter = dict(content.get("filter", {}))
        if content.get("subscribe", None) == "ranging":
            await self.channel_layer.group_add("mesh_msg_received", self.channel_name)
            self.msg_received_filter = {"msg_type": MeshMessageType.LOCATE_RANGE_RESULTS.name}
            await self.dump_newest_messages(MeshMessageType.LOCATE_RANGE_RESULTS)
        if content.get("subscribe", None) == "ota":
            await self.channel_layer.group_add("mesh_msg_received", self.channel_name)
            update_id = content.get("update_id", 0)
            self.msg_received_filter = {"msg_type": MeshMessageType.OTA_STATUS.name,
                                        "update_id": update_id}
            await self.channel_layer.group_add(MESH_ALL_OTA_GROUP, self.channel_name)
            await self.dump_newest_messages(MeshMessageType.OTA_STATUS)
            for recipient in await self._qs_as_list(OTAUpdateRecipient.objects.filter(update_id=update_id)):
                await self.send_json(recipient.get_status_json())
        if "ota_auto" in content:
            data = content["ota_auto"]
            recipient = await OTAUpdateRecipient.objects.aget(pk=content["recipient"])
            await OTASettingMessage(
                dst=recipient.node_id,
                src=MESH_ROOT_ADDRESS,
                update_id=recipient.update_id,
                auto_apply=data["apply"],
                auto_reboot=data["reboot"],
            ).send()

        if "ota" in content:
            ota = content["ota"]
            recipient = await OTAUpdateRecipient.objects.aget(pk=content["recipient"])
            if ota in ("apply", "reboot"):
                await OTAApplyMessage(
                    dst=recipient.node_id,
                    src=MESH_ROOT_ADDRESS,
                    update_id=recipient.update_id,
                    reboot=(ota == "reboot"),
                ).send()
            elif ota == "cancel":
                recipient.status = OTARecipientStatus.CANCELED
                await recipient.send_status()
                await OTAUpdateRecipient.objects.filter(pk=recipient.pk).aupdate(
                    status=OTARecipientStatus.CANCELED
                )
                await self.channel_layer.group_send(MESH_ALL_OTA_GROUP, {
                    "type": "mesh.ota_recipients_changed",
                    "addresses": [recipient.node_id]
                })

        if "send_msg" in content:
            msg_to_send = self.scope["session"].pop("mesh_msg_%s" % content["send_msg"], None)
            if not msg_to_send:
                return
            database_sync_to_async(self.scope["session"].save)()

            await self.channel_layer.group_add("mesh_msg_sent", self.channel_name)
            self.msg_sent_filter = {"sender": self.channel_name}

            if msg_to_send["msg_data"]["content"]["msg_type"] == MeshMessageType.MESH_ROUTE_REQUEST.name:
                await self.channel_layer.group_add("mesh_msg_received", self.channel_name)
                try:
                    self.msg_received_filter = {"request_id": msg_to_send["msg_data"]["content"]["request_id"]}
                except KeyError:
                    pass

            for recipient in msg_to_send["recipients"]:
                await MeshMessage.model_validate({
                    'dst': recipient,
                    **msg_to_send["msg_data"],
                }).send(sender=self.channel_name)

    async def dump_newest_messages(self, msg_type: MeshMessageType, include_ota=False):
        for msg in await self._get_last_messages(msg_type):
            await self.mesh_msg_received({
                "type": "mesh.msg_received",
                "msg": msg.data
            })

    @database_sync_to_async
    def _get_last_messages(self, msg_type):
        results = (node.last_messages[msg_type] for node in MeshNode.objects.prefetch_last_messages(msg_type))
        return [msg for msg in results if msg]

    @database_sync_to_async
    def _qs_as_list(self, qs):
        return list(qs)

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
        if data["msg"]["msg_type"] == MeshMessageType.LOCATE_RANGE_RESULTS.name:
            data = data.copy()
            location = await self.locator(data["msg"], data["msg"]["src"])
            data["position"] = None if not location else (int(location.x*100), int(location.y*100), int(location.z*100))
        await self.send_json(data)

    async def mesh_ota_recipient_status(self, data):
        await self.send_json(data)

    async def mesh_ota_recipients_changed(self, data):
        pass

    @database_sync_to_async
    def locator(self, msg, orig_addr=None):
        locator = Locator.load()
        return locator.locate_range(
            locator.convert_raw_scan_data([
                {
                    "bssid": r["peer"],
                    "ssid": "",
                    "rssi": r["rssi"],
                    "distance": r["distance"]
                }
                for r in msg["ranges"]
                if r["distance"] != 0xFFFF
            ]),
            permissions=None,
            orig_addr=orig_addr,
        )

    async def disconnect(self, code):
        await self.channel_layer.group_discard("mesh_log", self.channel_name)
        await self.channel_layer.group_discard("mesh_msg_sent", self.channel_name)
        await self.channel_layer.group_discard("mesh_msg_received", self.channel_name)
