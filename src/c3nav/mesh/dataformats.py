from dataclasses import dataclass, field
from enum import IntEnum, unique

from c3nav.mesh.baseformats import (BoolFormat, EnumFormat, FixedHexFormat, FixedStrFormat, SimpleFormat, StructType,
                                    VarArrayFormat)


class MacAddressFormat(FixedHexFormat):
    def __init__(self):
        super().__init__(num=6, sep=':')


class MacAddressesListFormat(VarArrayFormat):
    def __init__(self):
        super().__init__(child_type=MacAddressFormat())


@unique
class LedType(IntEnum):
    NONE = 0
    SERIAL = 1
    MULTIPIN = 2


@unique
class SerialLedType(IntEnum):
    WS2812 = 1
    SK6812 = 2


@dataclass
class LedConfig(StructType, union_type_field="led_type"):
    """
    configuration for an optional connected status LED
    """
    led_type: LedType = field(metadata={"format": EnumFormat(), "c_name": "type"})


@dataclass
class NoLedConfig(LedConfig, led_type=LedType.NONE):
    pass


@dataclass
class SerialLedConfig(LedConfig, led_type=LedType.SERIAL):
    serial_led_type: SerialLedType = field(metadata={"format": EnumFormat(), "c_name": "type"})
    gpio: int = field(metadata={"format": SimpleFormat('B')})


@dataclass
class MultipinLedConfig(LedConfig, led_type=LedType.MULTIPIN):
    gpio_red: int = field(metadata={"format": SimpleFormat('B')})
    gpio_green: int = field(metadata={"format": SimpleFormat('B')})
    gpio_blue: int = field(metadata={"format": SimpleFormat('B')})


@dataclass
class UWBConfig(StructType):
    """
    configuration for the connection to the UWB module
    """
    enable: bool = field(metadata={"format": BoolFormat()})
    gpio_miso: int = field(metadata={"format": SimpleFormat('B')})
    gpio_mosi: int = field(metadata={"format": SimpleFormat('B')})
    gpio_clk: int = field(metadata={"format": SimpleFormat('B')})
    gpio_cs: int = field(metadata={"format": SimpleFormat('B')})
    gpio_irq: int = field(metadata={"format": SimpleFormat('B')})
    gpio_rst: int = field(metadata={"format": SimpleFormat('B')})
    gpio_wakeup: int = field(metadata={"format": SimpleFormat('B')})
    gpio_exton: int = field(metadata={"format": SimpleFormat('B')})


@unique
class BoardType(IntEnum):
    CUSTOM = 0x00

    # devboards
    ESP32_C3_DEVKIT_M_1 = 0x01
    ESP32_C3_32S = 2

    # custom boards
    C3NAV_UWB_BOARD = 0x10
    C3NAV_LOCATION_PCB_REV_0_1 = 0x11
    C3NAV_LOCATION_PCB_REV_0_2 = 0x12


@dataclass
class BoardConfig(StructType, union_type_field="board"):
    board: BoardType = field(metadata={"format": EnumFormat(as_hex=True)})


@dataclass
class CustomBoardConfig(StructType, board=BoardType.CUSTOM):
    uwb: UWBConfig = field(metadata={"as_definition": True})
    led: LedConfig = field(metadata={"as_definition": True})


@dataclass
class DevkitMBoardConfig(StructType, board=BoardType.ESP32_C3_DEVKIT_M_1):
    uwb: UWBConfig = field(metadata={"as_definition": True})


@dataclass
class Esp32SBoardConfig(StructType, board=BoardType.ESP32_C3_32S):
    uwb: UWBConfig = field(metadata={"as_definition": True})


@dataclass
class UwbBoardConfig(StructType, board=BoardType.C3NAV_UWB_BOARD):
    pass


@dataclass
class LocationPCBRev0Dot1BoardConfig(StructType, board=BoardType.C3NAV_LOCATION_PCB_REV_0_1):
    pass


@dataclass
class LocationPCBRev0Dot2BoardConfig(StructType, board=BoardType.C3NAV_LOCATION_PCB_REV_0_2):
    pass


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
