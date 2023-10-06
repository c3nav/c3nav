from dataclasses import dataclass, field
from enum import IntEnum, unique

from c3nav.mesh.baseformats import FixedHexFormat, FixedStrFormat, SimpleFormat, StructType, VarArrayFormat


class MacAddressFormat(FixedHexFormat):
    def __init__(self):
        super().__init__(num=6, sep=':')


class MacAddressesListFormat(VarArrayFormat):
    def __init__(self):
        super().__init__(child_type=MacAddressFormat())


@unique
class LedType(IntEnum):
    SERIAL = 1
    MULTIPIN = 2


@dataclass
class LedConfig(StructType, union_type_field="led_type"):
    led_type: LedType = field(metadata={"format": SimpleFormat('B')})


@dataclass
class SerialLedConfig(LedConfig, led_type=LedType.SERIAL):
    gpio: int = field(metadata={"format": SimpleFormat('B')})
    rmt: int = field(metadata={"format": SimpleFormat('B')})


@dataclass
class MultipinLedConfig(LedConfig, led_type=LedType.MULTIPIN):
    gpio_red: int = field(metadata={"format": SimpleFormat('B')})
    gpio_green: int = field(metadata={"format": SimpleFormat('B')})
    gpio_blue: int = field(metadata={"format": SimpleFormat('B')})


@dataclass
class RangeItemType(StructType):
    address: str = field(metadata={"format": MacAddressFormat()})
    distance: int = field(metadata={"format": SimpleFormat('H')})


@dataclass
class FirmwareAppDescription(StructType, existing_c_struct="esp_app_desc_t"):
    magic_word: int = field(metadata={"format": SimpleFormat('I')}, repr=False)
    secure_version: int = field(metadata={"format": SimpleFormat('I')})
    reserv1: list[int] = field(metadata={"format": SimpleFormat('2I')}, repr=False)
    version: str = field(metadata={"format": FixedStrFormat(32)})
    project_name: str = field(metadata={"format": FixedStrFormat(32)})
    compile_time: str = field(metadata={"format": FixedStrFormat(16)})
    compile_date: str = field(metadata={"format": FixedStrFormat(16)})
    idf_version: str = field(metadata={"format": FixedStrFormat(32)})
    app_elf_sha256: str = field(metadata={"format": FixedHexFormat(32)})
    reserv2: list[int] = field(metadata={"format": SimpleFormat('20I')}, repr=False)
