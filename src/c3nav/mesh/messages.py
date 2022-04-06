import struct
from dataclasses import dataclass, field, fields

NO_LAYER = 0xFF
MAC_FMT = '%02x:%02x:%02x:%02x:%02x:%02x'


class SimpleFormat:
    def __init__(self, fmt):
        self.fmt = fmt
        self.size = struct.calcsize(fmt)

    def encode(self, value):
        return struct.pack(self.fmt, value)

    def decode(self, data: bytes):
        value = struct.unpack(self.fmt, data[:self.size])
        if len(value) == 1:
            value = value[0]
        return value, data[self.size:]


class FixedStrFormat:
    def __init__(self, num):
        self.num = num

    def encode(self, value):
        return struct.pack('%ss' % self.num, value)

    def decode(self, data: bytes):
        return struct.unpack('%ss' % self.num, data[:self.num])[0].rstrip(bytes((0, ))).decode(), data[self.num:]


class BoolFormat:
    def encode(self, value):
        return struct.pack('B', (int(value), ))

    def decode(self, data: bytes):
        return bool(struct.unpack('B', data[:1])[0]), data[1:]


class HexFormat:
    def __init__(self, num, sep=''):
        self.num = num
        self.sep = sep

    def encode(self, value):
        return struct.pack('%ss' % self.num, bytes.fromhex(value))

    def decode(self, data: bytes):
        return (
            struct.unpack('%ss' % self.num, data[:self.num])[0].hex(*([self.sep] if self.sep else [])),
            data[self.num:]
        )


class VarStrFormat:
    def encode(self, value: str) -> bytes:
        return bytes((len(value)+1, )) + value.encode() + bytes((0, ))

    def decode(self, data: bytes):
        return data[1:data[0]].decode(), data[data[0]+1:]


class MacAddressFormat:
    def encode(self, value: str) -> bytes:
        return bytes(int(value[i*3:i*3+2], 16) for i in range(6))

    def decode(self, data: bytes):
        return (MAC_FMT % tuple(data[:6])), data[6:]


class MacAddressesListFormat:
    def encode(self, value: list[str]) -> bytes:
        return bytes((len(value), )) + sum(
            (bytes((int(mac[i*3:i*3+2], 16) for i in range(6))) for mac in value),
            b''
        )

    def decode(self, data: bytes):
        return [MAC_FMT % tuple(data[1+6*i:1+6+6*i]) for i in range(data[0])], data[1+data[0]*6:]


class LedConfig:
    pass


@dataclass
class SerialLedConfig(LedConfig):
    type = 1
    gpio: int
    rmt: int


@dataclass
class MultipinLedConfig(LedConfig):
    type = 2
    gpio_red: int
    gpio_green: int
    gpio_blue: int


class LedConfigFormat:
    def encode(self, value) -> bytes:
        if value is None:
            return struct.pack('BBBB', (0, 0, 0, 0))
        if isinstance(value, SerialLedConfig):
            return struct.pack('BBBB', (value.type, value.gpio, value.rmt, 0))
        if isinstance(value, MultipinLedConfig):
            return struct.pack('BBBB', (value.type, value.gpio_red, value.gpio_green, value.gpio_blue))
        raise ValueError

    def decode(self, data: bytes):
        type_, *bytes_ = struct.unpack('BBBB', data)
        if type_ == 0:
            value = None
        elif type_ == 1:
            value = SerialLedConfig(gpio=bytes_[0], rmt=bytes_[1])
        elif type_ == 2:
            value = MultipinLedConfig(gpio_red=bytes_[0], gpio_green=bytes_[1], gpio_blue=bytes_[2])
        else:
            raise ValueError
        return value, data[4:]


@dataclass
class Message:
    dst: str = field(metadata={'format': MacAddressFormat()})
    src: str = field(metadata={'format': MacAddressFormat()})
    msg_id: int = field(metadata={'format': SimpleFormat('B')}, init=False, repr=True)
    msg_types = {}

    # noinspection PyMethodOverriding
    def __init_subclass__(cls, /, msg_id=None, **kwargs):
        super().__init_subclass__(**kwargs)
        if msg_id:
            cls.msg_id = msg_id
            Message.msg_types[msg_id] = cls

    def encode(self):
        data = bytes()
        for field_ in fields(self):
            data += field_.metadata['format'].encode(getattr(self, field_.name))
        return data

    @classmethod
    def decode(cls, data: bytes):
        print('decode', data.hex(' '))
        klass = cls.msg_types[data[12]]
        values = {}
        for field_ in fields(klass):
            values[field_.name], data = field_.metadata['format'].decode(data)
        values.pop('msg_id')
        return klass(**values)


@dataclass
class EchoRequestMessage(Message, msg_id=0x01):
    content: str = field(default='', metadata={'format': VarStrFormat()})


@dataclass
class EchoResponseMessage(Message, msg_id=0x02):
    content: str = field(default='', metadata={'format': VarStrFormat()})


@dataclass
class MeshSigninMessage(Message, msg_id=0x03):
    pass


@dataclass
class MeshLayerAnnounceMessage(Message, msg_id=0x04):
    layer: int = field(metadata={'format': SimpleFormat('B')})


@dataclass
class MeshAddDestinationsMessage(Message, msg_id=0x05):
    mac_addresses: list[str] = field(default_factory=list, metadata={'format': MacAddressesListFormat()})


@dataclass
class MeshRemoveDestinationsMessage(Message, msg_id=0x06):
    mac_addresses: list[str] = field(default_factory=list, metadata={'format': MacAddressesListFormat()})


@dataclass
class ConfigDumpMessage(Message, msg_id=0x10):
    pass


@dataclass
class ConfigFirmwareMessage(Message, msg_id=0x11):
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


@dataclass
class ConfigPositionMessage(Message, msg_id=0x12):
    x_pos: int = field(metadata={'format': SimpleFormat('I')})
    y_pos: int = field(metadata={'format': SimpleFormat('I')})
    z_pos: int = field(metadata={'format': SimpleFormat('H')})


@dataclass
class ConfigLedMessage(Message, msg_id=0x13):
    led_config: LedConfig = field(metadata={'format': LedConfigFormat()})


@dataclass
class ConfigUplinkMessage(Message, msg_id=0x14):
    enabled: bool = field(metadata={'format': BoolFormat()})
    ssid: str = field(metadata={'format': FixedStrFormat(32)})
    password: str = field(metadata={'format': FixedStrFormat(64)})
    channel: int = field(metadata={'format': SimpleFormat('B')})
    udp: bool = field(metadata={'format': BoolFormat()})
    ssl: bool = field(metadata={'format': BoolFormat()})
    host: str = field(metadata={'format': FixedStrFormat(64)})
    port: int = field(metadata={'format': SimpleFormat('H')})
