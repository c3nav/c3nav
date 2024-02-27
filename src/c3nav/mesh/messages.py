from dataclasses import dataclass, field
from enum import IntEnum, unique
from typing import TypeVar, Annotated

import channels
from channels.db import database_sync_to_async
from pydantic import Field as APIField
from pydantic import PositiveInt

from c3nav.api.utils import EnumSchemaByNameMixin
from c3nav.mesh.baseformats import (BoolFormat, EnumFormat, FixedStrFormat, SimpleFormat, StructType, VarArrayFormat,
                                    VarBytesFormat, VarStrFormat, normalize_name)
from c3nav.mesh.dataformats import (BoardConfig, ChipType, FirmwareAppDescription, MacAddressesListFormat,
                                    MacAddressFormat, RangeResultItem, RawFTMEntry)
from c3nav.mesh.utils import MESH_ALL_UPLINKS_GROUP

MESH_ROOT_ADDRESS = '00:00:00:00:00:00'
MESH_NONE_ADDRESS = '00:00:00:00:00:00'
MESH_PARENT_ADDRESS = '00:00:00:ff:ff:ff'
MESH_CHILDREN_ADDRESS = '00:00:00:00:ff:ff'
MESH_BROADCAST_ADDRESS = 'ff:ff:ff:ff:ff:ff'
NO_LAYER = 0xFF

OTA_CHUNK_SIZE = 512


@unique
class MeshMessageType(EnumSchemaByNameMixin, IntEnum):
    NOOP = 0x00

    ECHO_REQUEST = 0x01
    ECHO_RESPONSE = 0x02

    MESH_SIGNIN = 0x03
    MESH_LAYER_ANNOUNCE = 0x04
    MESH_ADD_DESTINATIONS = 0x05
    MESH_REMOVE_DESTINATIONS = 0x06
    MESH_ROUTE_REQUEST = 0x07
    MESH_ROUTE_RESPONSE = 0x08
    MESH_ROUTE_TRACE = 0x09
    MESH_ROUTING_FAILED = 0x0a

    CONFIG_DUMP = 0x10
    CONFIG_HARDWARE = 0x11
    CONFIG_BOARD = 0x12
    CONFIG_FIRMWARE = 0x13
    CONFIG_UPLINK = 0x14
    CONFIG_POSITION = 0x15

    OTA_STATUS = 0x20
    OTA_REQUEST_STATUS = 0x21
    OTA_START = 0x22
    OTA_URL = 0x23
    OTA_FRAGMENT = 0x24
    OTA_REQUEST_FRAGMENTS = 0x25
    OTA_SETTING = 0x26
    OTA_APPLY = 0x27
    OTA_ABORT = 0x28

    LOCATE_REQUEST_RANGE = 0x30
    LOCATE_RANGE_RESULTS = 0x31
    LOCATE_RAW_FTM_RESULTS = 0x32

    REBOOT = 0x40

    REPORT_ERROR = 0x50

    @property
    def pretty_name(self):
        name = self.name.replace('_', ' ').lower()
        if name.startswith('config'):
            name = name.removeprefix('config').strip() + ' config'
        name.replace('ota', 'OTA')
        return name


M = TypeVar('M', bound='MeshMessage')


@dataclass
class MeshMessage(StructType, union_type_field="msg_type"):
    dst: str = field(metadata={"format": MacAddressFormat()})
    src: str = field(metadata={"format": MacAddressFormat()})
    msg_type: MeshMessageType = field(metadata={"format": EnumFormat('B', c_definition=False)}, init=False, repr=False)
    c_structs = {}
    c_struct_name = None

    # noinspection PyMethodOverriding
    def __init_subclass__(cls, /, c_struct_name=None, **kwargs):
        super().__init_subclass__(**kwargs)
        if c_struct_name:
            cls.c_struct_name = c_struct_name
            if c_struct_name in MeshMessage.c_structs:
                raise TypeError('duplicate use of c_struct_name %s' % c_struct_name)
            MeshMessage.c_structs[c_struct_name] = cls

    async def send(self, sender=None, exclude_uplink_address=None) -> bool:
        data = {
            "type": "mesh.send",
            "sender": sender,
            "exclude_uplink_address": exclude_uplink_address,
            "msg": MeshMessage.tojson(self),
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

    @classmethod
    def get_ignore_c_fields(self):
        return set()

    @classmethod
    def get_additional_c_fields(self):
        return ()

    @classmethod
    def get_variable_name(cls, base_name):
        return cls.c_struct_name or base_name

    @classmethod
    def get_c_enum_name(cls):
        return normalize_name(cls.__name__.removeprefix('Mesh').removesuffix('Message')).upper()


@dataclass
class NoopMessage(MeshMessage, msg_type=MeshMessageType.NOOP):
    """ noop """
    pass


@dataclass
class EchoRequestMessage(MeshMessage, msg_type=MeshMessageType.ECHO_REQUEST):
    """ repeat back string """
    content: str = field(default='', metadata={'format': VarStrFormat(max_len=255)})


@dataclass
class EchoResponseMessage(MeshMessage, msg_type=MeshMessageType.ECHO_RESPONSE):
    """ repeat back string """
    content: str = field(default='', metadata={'format': VarStrFormat(max_len=255)})


@dataclass
class MeshSigninMessage(MeshMessage, msg_type=MeshMessageType.MESH_SIGNIN):
    """ node says hello to upstream node """
    pass


@dataclass
class MeshLayerAnnounceMessage(MeshMessage, msg_type=MeshMessageType.MESH_LAYER_ANNOUNCE):
    """ upstream node announces layer number """
    layer: Annotated[PositiveInt, APIField(lt=2**8)] = field(metadata={
        "format": SimpleFormat('B'),
        "doc": "mesh layer that the sending node is on",
    })


@dataclass
class MeshAddDestinationsMessage(MeshMessage, msg_type=MeshMessageType.MESH_ADD_DESTINATIONS):
    """ downstream node announces served destination """
    addresses: list[str] = field(default_factory=list, metadata={
        "format": MacAddressesListFormat(max_num=16),
        "doc": "adresses of the added destinations",
    })


@dataclass
class MeshRemoveDestinationsMessage(MeshMessage, msg_type=MeshMessageType.MESH_REMOVE_DESTINATIONS):
    """ downstream node announces no longer served destination """
    addresses: list[str] = field(default_factory=list, metadata={
        "format": MacAddressesListFormat(max_num=16),
        "doc": "adresses of the removed destinations",
    })


@dataclass
class MeshRouteRequestMessage(MeshMessage, msg_type=MeshMessageType.MESH_ROUTE_REQUEST):
    """ request routing information for node """
    request_id: Annotated[PositiveInt, APIField(lt=2**32)] = field(metadata={"format": SimpleFormat('I')})
    address: str = field(metadata={
        "format": MacAddressFormat(),
        "doc": "target address for the route"
    })


@dataclass
class MeshRouteResponseMessage(MeshMessage, msg_type=MeshMessageType.MESH_ROUTE_RESPONSE):
    """ reporting the routing table entry to the given address """
    request_id: Annotated[PositiveInt, APIField(lt=2**32)] = field(metadata={"format": SimpleFormat('I')})
    route: str = field(metadata={
        "format": MacAddressFormat(),
        "doc": "routing table entry or 00:00:00:00:00:00"
    })


@dataclass
class MeshRouteTraceMessage(MeshMessage, msg_type=MeshMessageType.MESH_ROUTE_TRACE):
    """ special message, collects all hop adresses on its way """
    request_id: Annotated[PositiveInt, APIField(lt=2**32)] = field(metadata={"format": SimpleFormat('I')})
    trace: list[str] = field(default_factory=list, metadata={
        "format": MacAddressesListFormat(max_num=16),
        "doc": "addresses encountered by this message",
    })


@dataclass
class MeshRoutingFailedMessage(MeshMessage, msg_type=MeshMessageType.MESH_ROUTING_FAILED):
    """ TODO description"""
    address: str = field(metadata={"format": MacAddressFormat()})


@dataclass
class ConfigDumpMessage(MeshMessage, msg_type=MeshMessageType.CONFIG_DUMP):
    """ request for the node to dump its config """
    pass


@dataclass
class ConfigHardwareMessage(MeshMessage, msg_type=MeshMessageType.CONFIG_HARDWARE):
    """ respond hardware/chip info """
    chip: ChipType = field(metadata={
        "format": EnumFormat("H", c_definition=False),
        "c_name": "chip_id",
    })
    revision_major: Annotated[PositiveInt, APIField(lt=2**8)] = field(metadata={"format": SimpleFormat('B')})
    revision_minor: Annotated[PositiveInt, APIField(lt=2**8)] = field(metadata={"format": SimpleFormat('B')})

    def get_chip_display(self):
        return ChipType(self.chip).name.replace('_', '-')


@dataclass
class ConfigBoardMessage(MeshMessage, msg_type=MeshMessageType.CONFIG_BOARD):
    """ set/respond board config """
    board_config: BoardConfig = field(metadata={"c_embed": True, "json_embed": True})


@dataclass
class ConfigFirmwareMessage(MeshMessage, msg_type=MeshMessageType.CONFIG_FIRMWARE):
    """ respond firmware info """
    app_desc: FirmwareAppDescription = field(metadata={'json_embed': True})


@dataclass
class ConfigPositionMessage(MeshMessage, msg_type=MeshMessageType.CONFIG_POSITION):
    """ set/respond position config """
    x_pos: Annotated[int, APIField(ge=-2**31, lt=2**31)] = field(metadata={"format": SimpleFormat('i')})
    y_pos: Annotated[int, APIField(ge=-2**31, lt=2**31)] = field(metadata={"format": SimpleFormat('i')})
    z_pos: Annotated[int, APIField(ge=-2**15, lt=2**15)] = field(metadata={"format": SimpleFormat('h')})


@dataclass
class ConfigUplinkMessage(MeshMessage, msg_type=MeshMessageType.CONFIG_UPLINK):
    """ set/respond uplink config """
    enabled: bool = field(metadata={"format": BoolFormat()})
    ssid: str = field(metadata={"format": FixedStrFormat(32)})
    password: str = field(metadata={"format": FixedStrFormat(64)})
    channel: Annotated[PositiveInt, APIField(le=15)] = field(metadata={"format": SimpleFormat('B')})
    udp: bool = field(metadata={"format": BoolFormat()})
    ssl: bool = field(metadata={"format": BoolFormat()})
    host: str = field(metadata={"format": FixedStrFormat(64)})
    port: Annotated[PositiveInt, APIField(lt=2**16)] = field(metadata={"format": SimpleFormat('H')})


@unique
class OTADeviceStatus(EnumSchemaByNameMixin, IntEnum):
    """ ota status, the ones >= 0x10 denote a permanent failure """
    NONE = 0x00

    STARTED = 0x01
    APPLIED = 0x02

    START_FAILED = 0x10
    WRITE_FAILED = 0x12
    APPLY_FAILED = 0x13
    ROLLED_BACK = 0x14

    @property
    def pretty_name(self):
        return self.name.replace('_', ' ').lower()

    @property
    def is_failed(self):
        return self >= self.START_FAILED


@dataclass
class OTAStatusMessage(MeshMessage, msg_type=MeshMessageType.OTA_STATUS):
    """ report OTA status """
    update_id: Annotated[PositiveInt, APIField(lt=2**32)] = field(metadata={"format": SimpleFormat('I')})
    received_bytes: Annotated[PositiveInt, APIField(lt=2**32)] = field(metadata={"format": SimpleFormat('I')})
    next_expected_chunk: Annotated[PositiveInt, APIField(lt=2**16)] = field(metadata={"format": SimpleFormat('H')})
    auto_apply: bool = field(metadata={"format": BoolFormat()})
    auto_reboot: bool = field(metadata={"format": BoolFormat()})
    status: OTADeviceStatus = field(metadata={"format": EnumFormat('B')})


@dataclass
class OTARequestStatusMessage(MeshMessage, msg_type=MeshMessageType.OTA_REQUEST_STATUS):
    """ request OTA status """
    pass


@dataclass
class OTAStartMessage(MeshMessage, msg_type=MeshMessageType.OTA_START):
    """ instruct node to start OTA """
    update_id: Annotated[PositiveInt, APIField(lt=2**32)] = field(metadata={"format": SimpleFormat('I')})
    total_bytes: Annotated[PositiveInt, APIField(lt=2**32)] = field(metadata={"format": SimpleFormat('I')})
    auto_apply: bool = field(metadata={"format": BoolFormat()})
    auto_reboot: bool = field(metadata={"format": BoolFormat()})


@dataclass
class OTAURLMessage(MeshMessage, msg_type=MeshMessageType.OTA_URL):
    """ supply download URL for OTA update and who to distribute it to """
    update_id: Annotated[PositiveInt, APIField(lt=2**32)] = field(metadata={"format": SimpleFormat('I')})
    distribute_to: str = field(metadata={"format": MacAddressFormat()})
    url: str = field(metadata={"format": VarStrFormat(max_len=255)})


@dataclass
class OTAFragmentMessage(MeshMessage, msg_type=MeshMessageType.OTA_FRAGMENT):
    """ supply OTA fragment """
    update_id: Annotated[PositiveInt, APIField(lt=2**32)] = field(metadata={"format": SimpleFormat('I')})
    chunk: Annotated[PositiveInt, APIField(lt=2**16)] = field(metadata={"format": SimpleFormat('H')})
    data: bytes = field(metadata={"format": VarBytesFormat(max_size=OTA_CHUNK_SIZE)})


@dataclass
class OTARequestFragmentsMessage(MeshMessage, msg_type=MeshMessageType.OTA_REQUEST_FRAGMENTS):
    """ request missing fragments """
    update_id: Annotated[PositiveInt, APIField(lt=2**32)] = field(metadata={"format": SimpleFormat('I')})
    chunks: list[int] = field(metadata={"format": VarArrayFormat(SimpleFormat('H'), max_num=128)})


@dataclass
class OTASettingMessage(MeshMessage, msg_type=MeshMessageType.OTA_SETTING):
    """ configure whether to automatically apply and reboot when update is completed """
    update_id: Annotated[PositiveInt, APIField(lt=2**32)] = field(metadata={"format": SimpleFormat('I')})
    auto_apply: bool = field(metadata={"format": BoolFormat()})
    auto_reboot: bool = field(metadata={"format": BoolFormat()})


@dataclass
class OTAApplyMessage(MeshMessage, msg_type=MeshMessageType.OTA_APPLY):
    """ apply OTA and optionally reboot """
    update_id: Annotated[PositiveInt, APIField(lt=2**32)] = field(metadata={"format": SimpleFormat('I')})
    reboot: bool = field(metadata={"format": BoolFormat()})


@dataclass
class OTAAbortMessage(MeshMessage, msg_type=MeshMessageType.OTA_ABORT):
    """ announcing OTA abort """
    update_id: Annotated[PositiveInt, APIField(lt=2**32)] = field(metadata={"format": SimpleFormat('I')})


@dataclass
class LocateRequestRangeMessage(MeshMessage, msg_type=MeshMessageType.LOCATE_REQUEST_RANGE):
    """ request to report distance to all nearby nodes """
    pass


@dataclass
class LocateRangeResults(MeshMessage, msg_type=MeshMessageType.LOCATE_RANGE_RESULTS):
    """ reports distance to given nodes """
    ranges: list[RangeResultItem] = field(metadata={"format": VarArrayFormat(RangeResultItem, max_num=16)})


@dataclass
class LocateRawFTMResults(MeshMessage, msg_type=MeshMessageType.LOCATE_RAW_FTM_RESULTS):
    """ reports distance to given nodes """
    peer: str = field(metadata={"format": MacAddressFormat()})
    results: list[RawFTMEntry] = field(metadata={"format": VarArrayFormat(RawFTMEntry, max_num=16)})


@dataclass
class Reboot(MeshMessage, msg_type=MeshMessageType.REBOOT):
    """ reboot the device """
    pass


@dataclass
class ReportError(MeshMessage, msg_type=MeshMessageType.REPORT_ERROR):
    """ report a critical error to upstream """
    message: str = field(metadata={"format": VarStrFormat(max_len=255)})
