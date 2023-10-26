import re
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

    @property
    def pretty_name(self):
        return self.name.lower()


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

    @property
    def pretty_name(self):
        if self.name.startswith('ESP32'):
            return self.name.replace('_', '-').replace('DEVKIT-', 'DevKit')
        if self.name.startswith('C3NAV'):
            name = self.name.replace('_', ' ').lower()
            name = name.replace('uwb', 'UWB').replace('pcb', 'PCB')
            name = re.sub(r'[0-9]+( [0-9+])+', lambda s: s[0].replace(' ', '.'), name)
            name = re.sub(r'rev.*', lambda s: s[0].replace(' ', ''), name)
            return name
        return self.name


@dataclass
class BoardConfig(StructType, union_type_field="board"):
    board: BoardType = field(metadata={"format": EnumFormat(as_hex=True)})


@dataclass
class CustomBoardConfig(BoardConfig, board=BoardType.CUSTOM):
    uwb: UWBConfig = field(metadata={"as_definition": True})
    led: LedConfig = field(metadata={"as_definition": True})


@dataclass
class DevkitMBoardConfig(BoardConfig, board=BoardType.ESP32_C3_DEVKIT_M_1):
    uwb: UWBConfig = field(metadata={"as_definition": True})


@dataclass
class Esp32SBoardConfig(BoardConfig, board=BoardType.ESP32_C3_32S):
    uwb: UWBConfig = field(metadata={"as_definition": True})


@dataclass
class UwbBoardConfig(BoardConfig, board=BoardType.C3NAV_UWB_BOARD):
    pass


@dataclass
class LocationPCBRev0Dot1BoardConfig(BoardConfig, board=BoardType.C3NAV_LOCATION_PCB_REV_0_1):
    pass


@dataclass
class LocationPCBRev0Dot2BoardConfig(BoardConfig, board=BoardType.C3NAV_LOCATION_PCB_REV_0_2):
    pass


@dataclass
class RangeResultItem(StructType):
    address: str = field(metadata={"format": MacAddressFormat()})
    distance: int = field(metadata={"format": SimpleFormat('H')})


@dataclass
class RawFTMEntry(StructType, existing_c_struct="wifi_ftm_report_entry_t"):
    dlog_token: int = field(metadata={"format": SimpleFormat('B')})
    rssi: int = field(metadata={"format": SimpleFormat('b')})
    rtt: int = field(metadata={"format": SimpleFormat('I')})
    t1: int = field(metadata={"format": SimpleFormat('Q')})
    t2: int = field(metadata={"format": SimpleFormat('Q')})
    t3: int = field(metadata={"format": SimpleFormat('Q')})
    t4: int = field(metadata={"format": SimpleFormat('Q')})


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
