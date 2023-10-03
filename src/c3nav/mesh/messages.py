from dataclasses import asdict, dataclass, field, fields, is_dataclass
from enum import IntEnum, unique
from typing import TypeVar

from c3nav.mesh.dataformats import (BoolFormat, FixedStrFormat, HexFormat, LedConfig, LedConfigFormat,
                                    MacAddressesListFormat, MacAddressFormat, SimpleFormat, VarStrFormat)

ROOT_ADDRESS = '00:00:00:00:00:00'
PARENT_ADDRESS = '00:00:00:ff:ff:ff'
NO_LAYER = 0xFF


@unique
class MessageType(IntEnum):
    ECHO_REQUEST = 0x01
    ECHO_RESPONSE = 0x02

    MESH_SIGNIN = 0x03
    MESH_LAYER_ANNOUNCE = 0x04
    MESH_ADD_DESTINATIONS = 0x05
    MESH_REMOVE_DESTINATIONS = 0x06

    CONFIG_DUMP = 0x10
    CONFIG_FIRMWARE = 0x11
    CONFIG_POSITION = 0x12
    CONFIG_LED = 0x13
    CONFIG_UPLINK = 0x14


M = TypeVar('M', bound='Message')


@unique
class ChipType(IntEnum):
    ESP32_S2 = 2
    ESP32_C3 = 5


@dataclass
class Message:
    dst: str = field(metadata={'format': MacAddressFormat()})
    src: str = field(metadata={'format': MacAddressFormat()})
    msg_id: int = field(metadata={'format': SimpleFormat('B')}, init=False, repr=False)
    msg_types = {}

    # noinspection PyMethodOverriding
    def __init_subclass__(cls, /, msg_id=None, **kwargs):
        super().__init_subclass__(**kwargs)
        if msg_id:
            cls.msg_id = msg_id
            if msg_id in Message.msg_types:
                raise TypeError('duplicate use of msg_id %d' % msg_id)
            Message.msg_types[msg_id] = cls

    def encode(self):
        data = bytes()
        for field_ in fields(self):
            data += field_.metadata['format'].encode(getattr(self, field_.name))
        return data

    @classmethod
    def decode(cls, data: bytes) -> M:
        # print('decode', data.hex(' '))
        klass = cls.msg_types[data[12]]
        values = {}
        for field_ in fields(klass):
            values[field_.name], data = field_.metadata['format'].decode(data)
        values.pop('msg_id')
        return klass(**values)

    def tojson(self):
        return asdict(self)

    @classmethod
    def fromjson(cls, data) -> M:
        kwargs = data.copy()
        klass = cls.msg_types[kwargs.pop('msg_id')]
        for field_ in fields(klass):
            if is_dataclass(field_.type):
                kwargs[field_.name] = field_.type.fromjson(kwargs[field_.name])
        return klass(**kwargs)


@dataclass
class EchoRequestMessage(Message, msg_id=MessageType.ECHO_REQUEST):
    content: str = field(default='', metadata={'format': VarStrFormat()})


@dataclass
class EchoResponseMessage(Message, msg_id=MessageType.ECHO_RESPONSE):
    content: str = field(default='', metadata={'format': VarStrFormat()})


@dataclass
class MeshSigninMessage(Message, msg_id=MessageType.MESH_SIGNIN):
    pass


@dataclass
class MeshLayerAnnounceMessage(Message, msg_id=MessageType.MESH_LAYER_ANNOUNCE):
    layer: int = field(metadata={'format': SimpleFormat('B')})


@dataclass
class MeshAddDestinationsMessage(Message, msg_id=MessageType.MESH_ADD_DESTINATIONS):
    mac_addresses: list[str] = field(default_factory=list, metadata={'format': MacAddressesListFormat()})


@dataclass
class MeshRemoveDestinationsMessage(Message, msg_id=MessageType.MESH_REMOVE_DESTINATIONS):
    mac_addresses: list[str] = field(default_factory=list, metadata={'format': MacAddressesListFormat()})


@dataclass
class ConfigDumpMessage(Message, msg_id=MessageType.CONFIG_DUMP):
    pass


@dataclass
class ConfigFirmwareMessage(Message, msg_id=MessageType.CONFIG_FIRMWARE):
    chip: int = field(metadata={'format': SimpleFormat('H')})
    revision: int = field(metadata={'format': SimpleFormat('2B')})
    magic_word: int = field(metadata={'format': SimpleFormat('I')}, repr=False)
    secure_version: int = field(metadata={'format': SimpleFormat('I')})
    reserv1: list[int] = field(metadata={'format': SimpleFormat('2I')}, repr=False)
    version: str = field(metadata={'format': FixedStrFormat(32)})
    project_name: str = field(metadata={'format': FixedStrFormat(32)})
    compile_time: str = field(metadata={'format': FixedStrFormat(16)})
    compile_date: str = field(metadata={'format': FixedStrFormat(16)})
    idf_version: str = field(metadata={'format': FixedStrFormat(32)})
    app_elf_sha256: str = field(metadata={'format': HexFormat(32)})
    reserv2: list[int] = field(metadata={'format': SimpleFormat('20I')}, repr=False)

    def to_model_data(self):
        return {
            'chip': self.chip,
            'project_name': self.project_name,
            'version': self.version,
            'idf_version': self.idf_version,
            'sha256_hash': self.app_elf_sha256,
        }

    def get_chip_display(self):
        return ChipType(self.chip).name.replace('_', '-')


@dataclass
class ConfigPositionMessage(Message, msg_id=MessageType.CONFIG_POSITION):
    x_pos: int = field(metadata={'format': SimpleFormat('I')})
    y_pos: int = field(metadata={'format': SimpleFormat('I')})
    z_pos: int = field(metadata={'format': SimpleFormat('H')})


@dataclass
class ConfigLedMessage(Message, msg_id=MessageType.CONFIG_LED):
    led_config: LedConfig = field(metadata={'format': LedConfigFormat()})


@dataclass
class ConfigUplinkMessage(Message, msg_id=MessageType.CONFIG_UPLINK):
    enabled: bool = field(metadata={'format': BoolFormat()})
    ssid: str = field(metadata={'format': FixedStrFormat(32)})
    password: str = field(metadata={'format': FixedStrFormat(64)})
    channel: int = field(metadata={'format': SimpleFormat('B')})
    udp: bool = field(metadata={'format': BoolFormat()})
    ssl: bool = field(metadata={'format': BoolFormat()})
    host: str = field(metadata={'format': FixedStrFormat(64)})
    port: int = field(metadata={'format': SimpleFormat('H')})
