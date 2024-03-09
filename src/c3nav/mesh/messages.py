from enum import unique
from typing import Annotated, Union

import channels
from annotated_types import Ge, Le, Lt, MaxLen
from channels.db import database_sync_to_async
from pydantic import PositiveInt
from pydantic.main import BaseModel
from pydantic.types import Discriminator
from pydantic_extra_types.mac_address import MacAddress

from c3nav.mesh.cformats import CDoc, CEmbed, CName, LenBytes, NoDef, VarLen, discriminator_value, CEnum
from c3nav.mesh.schemas import BoardConfig, ChipType, FirmwareAppDescription, RangeResultItem, RawFTMEntry
from c3nav.mesh.utils import MESH_ALL_UPLINKS_GROUP

MESH_ROOT_ADDRESS = '00:00:00:00:00:00'
MESH_NONE_ADDRESS = '00:00:00:00:00:00'
MESH_PARENT_ADDRESS = '00:00:00:ff:ff:ff'
MESH_CHILDREN_ADDRESS = '00:00:00:00:ff:ff'
MESH_BROADCAST_ADDRESS = 'ff:ff:ff:ff:ff:ff'
NO_LAYER = 0xFF

OTA_CHUNK_SIZE = 512


@unique
class MeshMessageType(CEnum):
    NOOP = "NOOP", 0x00

    ECHO_REQUEST = "ECHO_REQUEST", 0x01
    ECHO_RESPONSE = "ECHO_RESPONSE", 0x02

    MESH_SIGNIN = "MESH_SIGNIN", 0x03
    MESH_LAYER_ANNOUNCE = "MESH_LAYER_ANNOUNCE", 0x04
    MESH_ADD_DESTINATIONS = "MESH_ADD_DESTINATIONS", 0x05
    MESH_REMOVE_DESTINATIONS = "MESH_REMOVE_DESTINATIONS", 0x06
    MESH_ROUTE_REQUEST = "MESH_ROUTE_REQUEST", 0x07
    MESH_ROUTE_RESPONSE = "MESH_ROUTE_RESPONSE", 0x08
    MESH_ROUTE_TRACE = "MESH_ROUTE_TRACE", 0x09
    MESH_ROUTING_FAILED = "MESH_ROUTING_FAILED", 0x0a

    CONFIG_DUMP = "CONFIG_DUMP", 0x10
    CONFIG_HARDWARE = "CONFIG_HARDWARE", 0x11
    CONFIG_BOARD = "CONFIG_BOARD", 0x12
    CONFIG_FIRMWARE = "CONFIG_FIRMWARE", 0x13
    CONFIG_UPLINK = "CONFIG_UPLINK", 0x14
    CONFIG_POSITION = "CONFIG_POSITION", 0x15

    OTA_STATUS = "OTA_STATUS", 0x20
    OTA_REQUEST_STATUS = "OTA_REQUEST_STATUS", 0x21
    OTA_START = "OTA_START", 0x22
    OTA_URL = "OTA_URL", 0x23
    OTA_FRAGMENT = "OTA_FRAGMENT", 0x24
    OTA_REQUEST_FRAGMENTS = "OTA_REQUEST_FRAGMENTS", 0x25
    OTA_SETTING = "OTA_SETTING", 0x26
    OTA_APPLY = "OTA_APPLY", 0x27
    OTA_ABORT = "OTA_ABORT", 0x28

    LOCATE_REQUEST_RANGE = "LOCATE_REQUEST_RANGE", 0x30
    LOCATE_RANGE_RESULTS = "LOCATE_RANGE_RESULTS", 0x31
    LOCATE_RAW_FTM_RESULTS = "LOCATE_RAW_FTM_RESULTS", 0x32

    REBOOT = "REBOOT", 0x40

    REPORT_ERROR = "REPORT_ERROR", 0x50

    @property
    def pretty_name(self):
        name = self.name.replace('_', ' ').lower()
        if name.startswith('config'):
            name = name.removeprefix('config').strip() + ' config'
        name.replace('ota', 'OTA')
        return name


class NoopMessage(discriminator_value(msg_type=MeshMessageType.NOOP), BaseModel):
    """ noop """
    pass


class EchoRequestMessage(discriminator_value(msg_type=MeshMessageType.ECHO_REQUEST), BaseModel):
    """ repeat back string """
    content: Annotated[str, MaxLen(255), VarLen()] = ""


class EchoResponseMessage(discriminator_value(msg_type=MeshMessageType.ECHO_RESPONSE), BaseModel):
    """ repeat back string """
    content: Annotated[str, MaxLen(255), VarLen()] = ""


class MeshSigninMessage(discriminator_value(msg_type=MeshMessageType.MESH_SIGNIN), BaseModel):
    """ node says hello to upstream node """
    pass


class MeshLayerAnnounceMessage(discriminator_value(msg_type=MeshMessageType.MESH_LAYER_ANNOUNCE), BaseModel):
    """ upstream node announces layer number """
    layer: Annotated[PositiveInt, Lt(2 ** 8), CDoc("mesh layer that the sending node is on")]


class MeshAddDestinationsMessage(discriminator_value(msg_type=MeshMessageType.MESH_ADD_DESTINATIONS), BaseModel):
    """ downstream node announces served destination """
    addresses: Annotated[list[MacAddress], MaxLen(16), VarLen(), CDoc("adresses of the added destinations",)]


class MeshRemoveDestinationsMessage(discriminator_value(msg_type=MeshMessageType.MESH_REMOVE_DESTINATIONS), BaseModel):
    """ downstream node announces no longer served destination """
    addresses: Annotated[list[MacAddress], MaxLen(16), VarLen(), CDoc("adresses of the removed destinations",)]


class MeshRouteRequestMessage(discriminator_value(msg_type=MeshMessageType.MESH_ROUTE_REQUEST), BaseModel):
    """ request routing information for node """
    request_id: Annotated[PositiveInt, Lt(2**32)]
    address: Annotated[MacAddress, CDoc("target address for the route")]


class MeshRouteResponseMessage(discriminator_value(msg_type=MeshMessageType.MESH_ROUTE_RESPONSE), BaseModel):
    """ reporting the routing table entry to the given address """
    request_id: Annotated[PositiveInt, Lt(2**32)]
    route: Annotated[MacAddress, CDoc("routing table entry or 00:00:00:00:00:00")]


class MeshRouteTraceMessage(discriminator_value(msg_type=MeshMessageType.MESH_ROUTE_TRACE), BaseModel):
    """ special message, collects all hop adresses on its way """
    request_id: Annotated[PositiveInt, Lt(2**32)]
    trace: Annotated[list[MacAddress], MaxLen(16), VarLen(), CDoc("addresses encountered by this message")]


class MeshRoutingFailedMessage(discriminator_value(msg_type=MeshMessageType.MESH_ROUTING_FAILED), BaseModel):
    """ TODO description"""
    address: MacAddress


class ConfigDumpMessage(discriminator_value(msg_type=MeshMessageType.CONFIG_DUMP), BaseModel):
    """ request for the node to dump its config """
    pass


class ConfigHardwareMessage(discriminator_value(msg_type=MeshMessageType.CONFIG_HARDWARE), BaseModel):
    """ respond hardware/chip info """
    chip: Annotated[ChipType, NoDef(), LenBytes(2), CName("chip_id")]
    revision_major: Annotated[int, Lt(2**8)]
    revision_minor: Annotated[int, Lt(2**8)]

    def get_chip_display(self):
        return ChipType(self.chip).name.replace('_', '-')


class ConfigBoardMessage(discriminator_value(msg_type=MeshMessageType.CONFIG_BOARD), BaseModel):
    """ set/respond board config """
    board_config: Annotated[BoardConfig, CEmbed]


class ConfigFirmwareMessage(discriminator_value(msg_type=MeshMessageType.CONFIG_FIRMWARE), BaseModel):
    """ respond firmware info """
    app_desc: FirmwareAppDescription


class ConfigPositionMessage(discriminator_value(msg_type=MeshMessageType.CONFIG_POSITION), BaseModel):
    """ set/respond position config """
    x_pos: Annotated[int, Ge(-2**31), Lt(2**31)]
    y_pos: Annotated[int, Ge(-2**31), Lt(2**31)]
    z_pos: Annotated[int, Ge(-2**15), Lt(2**15)]


class ConfigUplinkMessage(discriminator_value(msg_type=MeshMessageType.CONFIG_UPLINK), BaseModel):
    """ set/respond uplink config """
    enabled: bool
    ssid: Annotated[str, MaxLen(32)]
    password: Annotated[str, MaxLen(64)]
    channel: Annotated[PositiveInt, Le(15)]
    udp: bool
    ssl: bool
    host: Annotated[str, MaxLen(64)]
    port: Annotated[PositiveInt, Lt(2**16)]


@unique
class OTADeviceStatus(CEnum):
    """ ota status, the ones >= 0x10 denote a permanent failure """
    NONE = "NONE", 0x00

    STARTED = "STARTED", 0x01
    APPLIED = "APPLIED", 0x02

    START_FAILED = "START_FAILED", 0x10
    WRITE_FAILED = "WRITE_FAILED", 0x12
    APPLY_FAILED = "APPLY_FAILED", 0x13
    ROLLED_BACK = "ROLLED_BACK", 0x14

    @property
    def pretty_name(self):
        return self.name.replace('_', ' ').lower()

    @property
    def is_failed(self):
        return self >= self.START_FAILED


class OTAStatusMessage(discriminator_value(msg_type=MeshMessageType.OTA_STATUS), BaseModel):
    """ report OTA status """
    update_id: Annotated[PositiveInt, Lt(2**32)]
    received_bytes: Annotated[PositiveInt, Lt(2**32)]
    next_expected_chunk: Annotated[PositiveInt, Lt(2**16)]
    auto_apply: bool
    auto_reboot: bool
    status: OTADeviceStatus


class OTARequestStatusMessage(discriminator_value(msg_type=MeshMessageType.OTA_REQUEST_STATUS), BaseModel):
    """ request OTA status """
    pass


class OTAStartMessage(discriminator_value(msg_type=MeshMessageType.OTA_START), BaseModel):
    """ instruct node to start OTA """
    update_id: Annotated[PositiveInt, Lt(2**32)]
    total_bytes: Annotated[PositiveInt, Lt(2**32)]
    auto_apply: bool
    auto_reboot: bool


class OTAURLMessage(discriminator_value(msg_type=MeshMessageType.OTA_URL), BaseModel):
    """ supply download URL for OTA update and who to distribute it to """
    update_id: Annotated[PositiveInt, Lt(2**32)]
    distribute_to: MacAddress
    url: Annotated[str, MaxLen(255), VarLen()]


class OTAFragmentMessage(discriminator_value(msg_type=MeshMessageType.OTA_FRAGMENT), BaseModel):
    """ supply OTA fragment """
    update_id: Annotated[PositiveInt, Lt(2**32)]
    chunk: Annotated[PositiveInt, Lt(2**16)]
    data: Annotated[bytes, MaxLen(OTA_CHUNK_SIZE), VarLen()]


class OTARequestFragmentsMessage(discriminator_value(msg_type=MeshMessageType.OTA_REQUEST_FRAGMENTS), BaseModel):
    """ request missing fragments """
    update_id: Annotated[PositiveInt, Lt(2**32)]
    chunks: Annotated[list[Annotated[PositiveInt, Lt(2**16)]], MaxLen(128), VarLen()]


class OTASettingMessage(discriminator_value(msg_type=MeshMessageType.OTA_SETTING), BaseModel):
    """ configure whether to automatically apply and reboot when update is completed """
    update_id: Annotated[PositiveInt, Lt(2**32)]
    auto_apply: bool
    auto_reboot: bool


class OTAApplyMessage(discriminator_value(msg_type=MeshMessageType.OTA_APPLY), BaseModel):
    """ apply OTA and optionally reboot """
    update_id: Annotated[PositiveInt, Lt(2**32)]
    reboot: bool


class OTAAbortMessage(discriminator_value(msg_type=MeshMessageType.OTA_ABORT), BaseModel):
    """ announcing OTA abort """
    update_id: Annotated[PositiveInt, Lt(2**32)]


class LocateRequestRangeMessage(discriminator_value(msg_type=MeshMessageType.LOCATE_REQUEST_RANGE), BaseModel):
    """ request to report distance to all nearby nodes """
    pass


class LocateRangeResults(discriminator_value(msg_type=MeshMessageType.LOCATE_RANGE_RESULTS), BaseModel):
    """ reports distance to given nodes """
    ranges: Annotated[list[RangeResultItem], MaxLen(16), VarLen()]


class LocateRawFTMResults(discriminator_value(msg_type=MeshMessageType.LOCATE_RAW_FTM_RESULTS), BaseModel):
    """ reports distance to given nodes """
    peer: MacAddress
    results: Annotated[list[RawFTMEntry], MaxLen(16), VarLen()]


class Reboot(discriminator_value(msg_type=MeshMessageType.REBOOT), BaseModel):
    """ reboot the device """
    pass


class ReportError(discriminator_value(msg_type=MeshMessageType.REPORT_ERROR), BaseModel):
    """ report a critical error to upstream """
    message: Annotated[str, MaxLen(255), VarLen()]


MeshMessageContent = Annotated[
    Union[
        NoopMessage,
        EchoRequestMessage,
        EchoResponseMessage,
        MeshSigninMessage,
        MeshLayerAnnounceMessage,
        MeshAddDestinationsMessage,
        MeshRemoveDestinationsMessage,
        MeshRouteRequestMessage,
        MeshRouteResponseMessage,
        MeshRouteTraceMessage,
        MeshRoutingFailedMessage,
        ConfigDumpMessage,
        ConfigHardwareMessage,
        ConfigBoardMessage,
        ConfigFirmwareMessage,
        ConfigPositionMessage,
        ConfigUplinkMessage,
        OTAStatusMessage,
        OTARequestStatusMessage,
        OTAStartMessage,
        OTAURLMessage,
        OTAFragmentMessage,
        OTARequestFragmentsMessage,
        OTASettingMessage,
        OTAApplyMessage,
        OTAAbortMessage,
        LocateRequestRangeMessage,
        LocateRangeResults,
        LocateRawFTMResults,
        Reboot,
        ReportError,
    ],
    Discriminator("msg_type")
]


class MeshMessage(BaseModel):
    dst: MacAddress
    src: MacAddress
    content: MeshMessageContent

    async def send(self, sender=None, exclude_uplink_address=None) -> bool:
        data = {
            "type": "mesh.send",
            "sender": sender,
            "exclude_uplink_address": exclude_uplink_address,
            "msg": self.model_dump(),
        }

        if self.dst in (MESH_CHILDREN_ADDRESS, MESH_BROADCAST_ADDRESS):
            await channels.layers.get_channel_layer().group_send(MESH_ALL_UPLINKS_GROUP, data)
            return True

        from c3nav.mesh.models import MeshNode
        uplink = await database_sync_to_async(MeshNode.get_node_and_uplink)(self.dst)
        if not uplink:
            return False
        if uplink.node_id == exclude_uplink_address:
            return False
        await channels.layers.get_channel_layer().send(uplink.name, data)