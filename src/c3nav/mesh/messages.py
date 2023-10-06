import re
from dataclasses import dataclass, field
from enum import IntEnum, unique
from typing import TypeVar

import channels
from asgiref.sync import async_to_sync

from c3nav.mesh.baseformats import BoolFormat, FixedStrFormat, SimpleFormat, StructType, VarArrayFormat, VarStrFormat
from c3nav.mesh.dataformats import (FirmwareAppDescription, LedConfig, MacAddressesListFormat, MacAddressFormat,
                                    RangeItemType)
from c3nav.mesh.utils import get_mesh_comm_group

MESH_ROOT_ADDRESS = '00:00:00:00:00:00'
MESH_NONE_ADDRESS = '00:00:00:00:00:00'
MESH_PARENT_ADDRESS = '00:00:00:ff:ff:ff'
MESH_CHILDREN_ADDRESS = '00:00:00:00:ff:ff'
MESH_BROADCAST_ADDRESS = 'ff:ff:ff:ff:ff:ff'
NO_LAYER = 0xFF


@unique
class MeshMessageType(IntEnum):
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
    CONFIG_FIRMWARE = 0x11
    CONFIG_POSITION = 0x12
    CONFIG_LED = 0x13
    CONFIG_UPLINK = 0x14

    LOCATE_REPORT_RANGE = 0x20


M = TypeVar('M', bound='MeshMessage')


@unique
class ChipType(IntEnum):
    ESP32_S2 = 2
    ESP32_C3 = 5


@dataclass
class MeshMessage(StructType, union_type_field="msg_id"):
    dst: str = field(metadata={"format": MacAddressFormat()})
    src: str = field(metadata={"format": MacAddressFormat()})
    msg_id: int = field(metadata={"format": SimpleFormat('B')}, init=False, repr=False)
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

    def send(self, sender=None, exclude_uplink_address=None):
        async_to_sync(channels.layers.get_channel_layer().group_send)(get_mesh_comm_group(self.dst), {
            "type": "mesh.send",
            "sender": sender,
            "exclude_uplink_address": exclude_uplink_address,
            "msg": MeshMessage.tojson(self),
        })

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
    def get_struct_name(cls, base_name):
        return "mesh_msg_%s_t" % base_name

    @classmethod
    def get_c_enum_name(cls):
        return re.sub(
            r"([a-z])([A-Z])",
            r"\1_\2",
            cls.__name__.removeprefix('Mesh').removesuffix('Message')
        ).upper().replace('CONFIG', 'CFG').replace('FIRMWARE', 'FW').replace('POSITION', 'POS')


@dataclass
class NoopMessage(MeshMessage, msg_id=MeshMessageType.NOOP):
    """ noop """
    pass


@dataclass
class BaseEchoMessage(MeshMessage, c_struct_name="echo"):
    """ repeat back string """
    content: str = field(default='', metadata={
        "format": VarStrFormat(),
        "doc": "string to echo",
        "c_name": "str",
    })


@dataclass
class EchoRequestMessage(BaseEchoMessage, msg_id=MeshMessageType.ECHO_REQUEST):
    """ repeat back string """
    pass


@dataclass
class EchoResponseMessage(BaseEchoMessage, msg_id=MeshMessageType.ECHO_RESPONSE):
    """ repeat back string """
    pass


@dataclass
class MeshSigninMessage(MeshMessage, msg_id=MeshMessageType.MESH_SIGNIN):
    """ node says hello to upstream node """
    pass


@dataclass
class MeshLayerAnnounceMessage(MeshMessage, msg_id=MeshMessageType.MESH_LAYER_ANNOUNCE):
    """ upstream node announces layer number """
    layer: int = field(metadata={
        "format": SimpleFormat('B'),
        "doc": "mesh layer that the sending node is on",
    })


@dataclass
class BaseDestinationsMessage(MeshMessage, c_struct_name="destinations"):
    """ downstream node announces served/no longer served destination """
    addresses: list[str] = field(default_factory=list, metadata={
        "format": MacAddressesListFormat(),
        "doc": "adresses of the destinations",
        "c_name": "addresses",
    })


@dataclass
class MeshAddDestinationsMessage(BaseDestinationsMessage, msg_id=MeshMessageType.MESH_ADD_DESTINATIONS):
    """ downstream node announces served destination """
    pass


@dataclass
class MeshRemoveDestinationsMessage(BaseDestinationsMessage, msg_id=MeshMessageType.MESH_REMOVE_DESTINATIONS):
    """ downstream node announces no longer served destination """
    pass


@dataclass
class MeshRouteRequestMessage(MeshMessage, msg_id=MeshMessageType.MESH_ROUTE_REQUEST):
    """ request routing information for node """
    request_id: int = field(metadata={"format": SimpleFormat('I')})
    address: str = field(metadata={
        "format": MacAddressFormat(),
        "doc": "target address for the route"
    })


@dataclass
class MeshRouteResponseMessage(MeshMessage, msg_id=MeshMessageType.MESH_ROUTE_RESPONSE):
    """ reporting the routing table entry to the given address """
    request_id: int = field(metadata={"format": SimpleFormat('I')})
    route: str = field(metadata={
        "format": MacAddressFormat(),
        "doc": "routing table entry or 00:00:00:00:00:00"
    })


@dataclass
class MeshRouteTraceMessage(MeshMessage, msg_id=MeshMessageType.MESH_ROUTE_TRACE):
    """ special message, collects all hop adresses on its way """
    request_id: int = field(metadata={"format": SimpleFormat('I')})
    trace: list[str] = field(default_factory=list, metadata={
        "format": MacAddressesListFormat(),
        "doc": "addresses encountered by this message",
    })


@dataclass
class MeshRoutingFailedMessage(MeshMessage, msg_id=MeshMessageType.MESH_ROUTING_FAILED):
    """ TODO description"""
    address: str = field(metadata={"format": MacAddressFormat()})


@dataclass
class ConfigDumpMessage(MeshMessage, msg_id=MeshMessageType.CONFIG_DUMP):
    """ request for the node to dump its config """
    pass


@dataclass
class ConfigFirmwareMessage(MeshMessage, msg_id=MeshMessageType.CONFIG_FIRMWARE):
    """ respond firmware info """
    chip: int = field(metadata={
        "format": SimpleFormat('H'),
        "c_name": "chip_id",
    })
    revision_major: int = field(metadata={"format": SimpleFormat('B')})
    revision_minor: int = field(metadata={"format": SimpleFormat('B')})
    app_desc: FirmwareAppDescription = field(metadata={'json_embed': True})

    @classmethod
    def upgrade_json(cls, data):
        if 'revision' in data:
            data['revision_major'], data['revision_minor'] = data.pop('revision')
        return data

    def get_chip_display(self):
        return ChipType(self.chip).name.replace('_', '-')

    @classmethod
    def get_ignore_c_fields(self):
        return {
            "magic_word", "secure_version", "reserv1", "version", "project_name",
            "compile_time", "compile_date", "idf_version", "app_elf_sha256", "reserv2"
        }

    @classmethod
    def get_additional_c_fields(self):
        return ("esp_app_desc_t app_desc;", )


@dataclass
class ConfigPositionMessage(MeshMessage, msg_id=MeshMessageType.CONFIG_POSITION):
    """ set/respond position config """
    x_pos: int = field(metadata={"format": SimpleFormat('i')})
    y_pos: int = field(metadata={"format": SimpleFormat('i')})
    z_pos: int = field(metadata={"format": SimpleFormat('h')})


@dataclass
class ConfigLedMessage(MeshMessage, msg_id=MeshMessageType.CONFIG_LED):
    """ set/respond led config """
    led_config: LedConfig = field(metadata={"c_embed": True})


@dataclass
class ConfigUplinkMessage(MeshMessage, msg_id=MeshMessageType.CONFIG_UPLINK):
    """ set/respond uplink config """
    enabled: bool = field(metadata={"format": BoolFormat()})
    ssid: str = field(metadata={"format": FixedStrFormat(32)})
    password: str = field(metadata={"format": FixedStrFormat(64)})
    channel: int = field(metadata={"format": SimpleFormat('B')})
    udp: bool = field(metadata={"format": BoolFormat()})
    ssl: bool = field(metadata={"format": BoolFormat()})
    host: str = field(metadata={"format": FixedStrFormat(64)})
    port: int = field(metadata={"format": SimpleFormat('H')})


@dataclass
class LocateReportRangeMessage(MeshMessage, msg_id=MeshMessageType.LOCATE_REPORT_RANGE):
    """ report distance to given nodes """
    ranges: dict[str, int] = field(metadata={"format": VarArrayFormat(RangeItemType)})
