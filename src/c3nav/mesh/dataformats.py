import struct
from dataclasses import dataclass, field
from enum import IntEnum

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


class LedType(IntEnum):
    SERIAL = 1
    MULTIPIN = 2


@dataclass
class LedConfig:
    led_type: LedType = field(init=False, repr=False)
    ledconfig_types = {}

    # noinspection PyMethodOverriding
    def __init_subclass__(cls, /, led_type: LedType, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.led_type = led_type
        LedConfig.ledconfig_types[led_type] = cls

    @classmethod
    def fromjson(cls, data):
        if data is None:
            return None
        return LedConfig.ledconfig_types[data.pop('led_type')](**data)


@dataclass
class SerialLedConfig(LedConfig, led_type=LedType.SERIAL):
    gpio: int
    rmt: int


@dataclass
class MultipinLedConfig(LedConfig, led_type=LedType.MULTIPIN):
    gpio_red: int
    gpio_green: int
    gpio_blue: int


class LedConfigFormat:
    def encode(self, value) -> bytes:
        if value is None:
            return struct.pack('BBBB', (0, 0, 0, 0))
        if isinstance(value, SerialLedConfig):
            return struct.pack('BBBB', (value.type_id, value.gpio, value.rmt, 0))
        if isinstance(value, MultipinLedConfig):
            return struct.pack('BBBB', (value.type_id, value.gpio_red, value.gpio_green, value.gpio_blue))
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

    def from_json(self, value):
        if value is None:
            return None

        type_ = value.pop('type')
        if type_ == 'serial':
            return SerialLedConfig(**value)
        elif type_ == 'multipin':
            return MultipinLedConfig(**value)
        raise ValueError
