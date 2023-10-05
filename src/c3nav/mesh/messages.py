import re
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from enum import IntEnum, unique
from itertools import chain
from typing import TypeVar

import channels
from asgiref.sync import async_to_sync

from c3nav.mesh.utils import get_mesh_comm_group, indent_c
from c3nav.mesh.dataformats import (BoolFormat, FixedStrFormat, HexFormat, LedConfig, LedConfigFormat,
                                    MacAddressesListFormat, MacAddressFormat, SimpleFormat, VarStrFormat)

MESH_ROOT_ADDRESS = '00:00:00:00:00:00'
MESH_PARENT_ADDRESS = '00:00:00:ff:ff:ff'
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

    CONFIG_DUMP = 0x10
    CONFIG_FIRMWARE = 0x11
    CONFIG_POSITION = 0x12
    CONFIG_LED = 0x13
    CONFIG_UPLINK = 0x14


M = TypeVar('M', bound='MeshMessage')


@unique
class ChipType(IntEnum):
    ESP32_S2 = 2
    ESP32_C3 = 5


@dataclass
class MeshMessage:
    dst: str = field(metadata={"format": MacAddressFormat()})
    src: str = field(metadata={"format": MacAddressFormat()})
    msg_id: int = field(metadata={"format": SimpleFormat('B')}, init=False, repr=False)
    msg_types = {}
    c_structs = {}
    c_struct_name = None

    # noinspection PyMethodOverriding
    def __init_subclass__(cls, /, msg_id=None, c_struct_name=None, **kwargs):
        super().__init_subclass__(**kwargs)
        if msg_id is not None:
            cls.msg_id = msg_id
            if msg_id in MeshMessage.msg_types:
                raise TypeError('duplicate use of msg_id %d' % msg_id)
            MeshMessage.msg_types[msg_id] = cls
        if c_struct_name:
            cls.c_struct_name = c_struct_name
            if c_struct_name in MeshMessage.c_structs:
                raise TypeError('duplicate use of c_struct_name %s' % c_struct_name)
            MeshMessage.c_structs[c_struct_name] = cls

    def encode(self):
        data = bytes()
        for field_ in fields(self):
            data += field_.metadata["format"].encode(getattr(self, field_.name))
        return data

    @classmethod
    def decode(cls, data: bytes) -> M:
        klass = cls.msg_types[data[12]]
        values = {}
        for field_ in fields(klass):
            values[field_.name], data = field_.metadata["format"].decode(data)
        values.pop('msg_id')
        return klass(**values)

    def tojson(self):
        return asdict(self)

    @classmethod
    def fromjson(cls, data) -> M:
        kwargs = data.copy()
        klass = cls.msg_types[kwargs.pop('msg_id')]
        kwargs = klass.upgrade_json(kwargs)
        for field_ in fields(klass):
            if is_dataclass(field_.type):
                kwargs[field_.name] = field_.type.fromjson(kwargs[field_.name])
        return klass(**kwargs)

    @classmethod
    def upgrade_json(cls, data):
        return data

    def send(self, sender=None):
        async_to_sync(channels.layers.get_channel_layer().group_send)(get_mesh_comm_group(self.dst), {
            "type": "mesh.send",
            "sender": sender,
            "msg": self.tojson()
        })

    @classmethod
    def get_ignore_c_fields(self):
        return set()

    @classmethod
    def get_additional_c_fields(self):
        return ()

    @classmethod
    def get_c_struct(cls):
        ignore_fields = cls.get_ignore_c_fields()
        if cls != MeshMessage:
            ignore_fields |= set(field.name for field in fields(MeshMessage))

        items = tuple(
            (
                tuple(field.metadata["format"].get_c_struct(field.metadata.get("c_name", field.name)).split("\n")),
                field.metadata.get("doc", None),
            )
            for field in fields(cls)
            if field.name not in ignore_fields
        )
        if not items:
            return ""
        max_line_len = max(len(line) for line in chain(*(code for code, doc in items)))

        msg_comment = cls.__doc__.strip()

        return "%(comment)stypedef struct __packed {\n%(elements)s\n} %(name)s;" % {
            "comment": ("/** %s */\n" % msg_comment) if msg_comment else "",
            "elements": indent_c(
                "\n".join(chain(*(
                    (code if not comment
                     else (code[:-1]+("%s /** %s */" % (code[-1].ljust(max_line_len), comment),)))
                    for code, comment in items
                ), cls.get_additional_c_fields()))
            ),
            "name": "mesh_msg_%s_t" % cls.get_c_struct_name(),
        }

    @classmethod
    def get_var_num(cls):
        return sum((getattr(field.metadata["format"], "var_num", 0) for field in fields(cls)), start=0)

    @classmethod
    def get_c_struct_name(cls):
        return (
            cls.c_struct_name if cls.c_struct_name else
            re.sub(
                r"([a-z])([A-Z])",
                r"\1_\2",
                cls.__name__.removeprefix('Mesh').removesuffix('Message')
            ).lower().replace('config', 'cfg').replace('firmware', 'fw').replace('position', 'pos')
        )

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
    magic_word: int = field(metadata={"format": SimpleFormat('I')}, repr=False)
    secure_version: int = field(metadata={"format": SimpleFormat('I')})
    reserv1: list[int] = field(metadata={"format": SimpleFormat('2I')}, repr=False)
    version: str = field(metadata={"format": FixedStrFormat(32)})
    project_name: str = field(metadata={"format": FixedStrFormat(32)})
    compile_time: str = field(metadata={"format": FixedStrFormat(16)})
    compile_date: str = field(metadata={"format": FixedStrFormat(16)})
    idf_version: str = field(metadata={"format": FixedStrFormat(32)})
    app_elf_sha256: str = field(metadata={"format": HexFormat(32)})
    reserv2: list[int] = field(metadata={"format": SimpleFormat('20I')}, repr=False)

    @classmethod
    def upgrade_json(cls, data):
        data = data.copy()  # todo: deepcopy?
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
    led_config: LedConfig = field(metadata={"format": LedConfigFormat()})


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
