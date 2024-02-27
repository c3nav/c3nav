import re
from dataclasses import dataclass, field
from enum import IntEnum, unique
from typing import BinaryIO, Self, Annotated, Literal

from pydantic import Field as APIField
from pydantic import NegativeInt, PositiveInt

from c3nav.api.utils import EnumSchemaByNameMixin
from c3nav.mesh.baseformats import (BoolFormat, ChipRevFormat, EnumFormat, FixedHexFormat, FixedStrFormat,
                                    SimpleConstFormat, SimpleFormat, StructType, TwoNibblesEnumFormat, VarArrayFormat)


class MacAddressFormat(FixedHexFormat):
    def __init__(self):
        super().__init__(num=6, sep=':')


class MacAddressesListFormat(VarArrayFormat):
    def __init__(self, max_num):
        super().__init__(child_type=MacAddressFormat(), max_num=max_num)


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
    gpio: Annotated[PositiveInt, APIField(lt=2**8)] = field(metadata={"format": SimpleFormat('B')})


@dataclass
class MultipinLedConfig(LedConfig, led_type=LedType.MULTIPIN):
    gpio_red: Annotated[PositiveInt, APIField(lt=2**8)] = field(metadata={"format": SimpleFormat('B')})
    gpio_green: Annotated[PositiveInt, APIField(lt=2**8)] = field(metadata={"format": SimpleFormat('B')})
    gpio_blue: Annotated[PositiveInt, APIField(lt=2**8)] = field(metadata={"format": SimpleFormat('B')})


@dataclass
class BoardSPIConfig(StructType):
    """
    configuration for spi bus used for ETH or UWB
    """
    gpio_miso: Annotated[PositiveInt, APIField(lt=2**8)] = field(metadata={"format": SimpleFormat('B')})
    gpio_mosi: Annotated[PositiveInt, APIField(lt=2**8)] = field(metadata={"format": SimpleFormat('B')})
    gpio_clk: Annotated[PositiveInt, APIField(lt=2**8)] = field(metadata={"format": SimpleFormat('B')})


@dataclass
class UWBConfig(StructType):
    """
    configuration for the connection to the UWB module
    """
    enable: bool = field(metadata={"format": BoolFormat()})
    gpio_cs: Annotated[PositiveInt, APIField(lt=2**8)] = field(metadata={"format": SimpleFormat('B')})
    gpio_irq: Annotated[PositiveInt, APIField(lt=2**8)] = field(metadata={"format": SimpleFormat('B')})
    gpio_rst: Annotated[PositiveInt, APIField(lt=2**8)] = field(metadata={"format": SimpleFormat('B')})
    gpio_wakeup: Annotated[PositiveInt, APIField(lt=2**8)] = field(metadata={"format": SimpleFormat('B')})
    gpio_exton: Annotated[PositiveInt, APIField(lt=2**8)] = field(metadata={"format": SimpleFormat('B')})


@dataclass
class UplinkEthConfig(StructType):
    """
    configuration for the connection to the ETH module
    """
    enable: bool = field(metadata={"format": BoolFormat()})
    gpio_cs: Annotated[PositiveInt, APIField(lt=2**8)] = field(metadata={"format": SimpleFormat('B')})
    gpio_int: Annotated[PositiveInt, APIField(lt=2**8)] = field(metadata={"format": SimpleFormat('B')})
    gpio_rst: Annotated[int, APIField(ge=-1, lt=2**7)] = field(metadata={"format": SimpleFormat('b')})


@unique
class BoardType(EnumSchemaByNameMixin, IntEnum):
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
    spi: BoardSPIConfig = field(metadata={"as_definition": True})
    uwb: UWBConfig = field(metadata={"as_definition": True})
    eth: UplinkEthConfig = field(metadata={"as_definition": True})
    led: LedConfig = field(metadata={"as_definition": True})


@dataclass
class DevkitMBoardConfig(BoardConfig, board=BoardType.ESP32_C3_DEVKIT_M_1):
    spi: BoardSPIConfig = field(metadata={"as_definition": True})
    uwb: UWBConfig = field(metadata={"as_definition": True})
    eth: UplinkEthConfig = field(metadata={"as_definition": True})


@dataclass
class Esp32SBoardConfig(BoardConfig, board=BoardType.ESP32_C3_32S):
    spi: BoardSPIConfig = field(metadata={"as_definition": True})
    uwb: UWBConfig = field(metadata={"as_definition": True})
    eth: UplinkEthConfig = field(metadata={"as_definition": True})


@dataclass
class UwbBoardConfig(BoardConfig, board=BoardType.C3NAV_UWB_BOARD):
    eth: UplinkEthConfig = field(metadata={"as_definition": True})


@dataclass
class LocationPCBRev0Dot1BoardConfig(BoardConfig, board=BoardType.C3NAV_LOCATION_PCB_REV_0_1):
    eth: UplinkEthConfig = field(metadata={"as_definition": True})


@dataclass
class LocationPCBRev0Dot2BoardConfig(BoardConfig, board=BoardType.C3NAV_LOCATION_PCB_REV_0_2):
    eth: UplinkEthConfig = field(metadata={"as_definition": True})


@dataclass
class RangeResultItem(StructType):
    peer: str = field(metadata={"format": MacAddressFormat()})
    rssi: Annotated[NegativeInt, APIField(gt=-100)] = field(metadata={"format": SimpleFormat('b')})
    distance: Annotated[int, APIField(gt=-32000, lt=32000)] = field(metadata={"format": SimpleFormat('h')})


@dataclass
class RawFTMEntry(StructType):
    dlog_token: Annotated[PositiveInt, APIField(lt=255)] = field(metadata={"format": SimpleFormat('B')})
    rssi: Annotated[NegativeInt, APIField(gt=-100)] = field(metadata={"format": SimpleFormat('b')})
    rtt: Annotated[PositiveInt, APIField(lt=2**32)] = field(metadata={"format": SimpleFormat('I')})
    t1: Annotated[PositiveInt, APIField(lt=2**64)] = field(metadata={"format": SimpleFormat('Q')})
    t2: Annotated[PositiveInt, APIField(lt=2**64)] = field(metadata={"format": SimpleFormat('Q')})
    t3: Annotated[PositiveInt, APIField(lt=2**64)] = field(metadata={"format": SimpleFormat('Q')})
    t4: Annotated[PositiveInt, APIField(lt=2**64)] = field(metadata={"format": SimpleFormat('Q')})


@dataclass
class FirmwareAppDescription(StructType, existing_c_struct="esp_app_desc_t", c_includes=['<esp_app_desc.h>']):
    magic_word: Literal[0xAB_CD_54_32] = field(metadata={"format": SimpleConstFormat('I', 0xAB_CD_54_32)}, repr=False)
    secure_version: Annotated[PositiveInt, APIField(lt=2**32)] = field(metadata={"format": SimpleFormat('I')})
    reserv1: list[int] = field(metadata={"format": SimpleFormat('2I')}, repr=False)
    version: str = field(metadata={"format": FixedStrFormat(32)})
    project_name: str = field(metadata={"format": FixedStrFormat(32)})
    compile_time: str = field(metadata={"format": FixedStrFormat(16)})
    compile_date: str = field(metadata={"format": FixedStrFormat(16)})
    idf_version: str = field(metadata={"format": FixedStrFormat(32)})
    app_elf_sha256: str = field(metadata={"format": FixedHexFormat(32)})
    reserv2: list[int] = field(metadata={"format": SimpleFormat('20I')}, repr=False)


@unique
class SPIFlashMode(EnumSchemaByNameMixin, IntEnum):
    QIO = 0
    QOUT = 1
    DIO = 2
    DOUT = 3


@unique
class FlashSize(EnumSchemaByNameMixin, IntEnum):
    SIZE_1MB = 0
    SIZE_2MB = 1
    SIZE_4MB = 2
    SIZE_8MB = 3
    SIZE_16MB = 4
    SIZE_32MB = 5
    SIZE_64MB = 6
    SIZE_128MB = 7

    @property
    def pretty_name(self):
        return self.name.removeprefix('SIZE_')


@unique
class FlashFrequency(EnumSchemaByNameMixin, IntEnum):
    FREQ_40MHZ = 0
    FREQ_26MHZ = 1
    FREQ_20MHZ = 2
    FREQ_80MHZ = 0xf

    @property
    def pretty_name(self):
        return self.name.removeprefix('FREQ_').replace('MHZ', 'Mhz')


@dataclass
class FlashSettings:
    size: FlashSize
    frequency: FlashFrequency

    @property
    def display(self):
        return f"{self.size.pretty_name} ({self.frequency.pretty_name})"


@unique
class ChipType(EnumSchemaByNameMixin, IntEnum):
    ESP32_S2 = 2
    ESP32_C3 = 5

    @property
    def pretty_name(self):
        return self.name.replace('_', '-')


@dataclass
class FirmwareImageFileHeader(StructType):
    magic_word: Literal[0xE9] = field(metadata={"format": SimpleConstFormat('B', 0xE9)}, repr=False)
    num_segments: int = field(metadata={"format": SimpleFormat('B')})
    spi_flash_mode: SPIFlashMode = field(metadata={"format": EnumFormat()})
    flash_stuff: FlashSettings = field(metadata={"format": TwoNibblesEnumFormat()})
    entry_point: int = field(metadata={"format": SimpleFormat('I')})


@dataclass
class FirmwareImageExtendedFileHeader(StructType):
    wp_pin: int = field(metadata={"format": SimpleFormat('B')})
    drive_settings: int = field(metadata={"format": SimpleFormat('3B')})
    chip: ChipType = field(metadata={"format": EnumFormat('H')})
    min_chip_rev_old: int = field(metadata={"format": SimpleFormat('B')})
    min_chip_rev: tuple[int, int] = field(metadata={"format": ChipRevFormat()})
    max_chip_rev: tuple[int, int] = field(metadata={"format": ChipRevFormat()})
    reserv: int = field(metadata={"format": SimpleFormat('I')}, repr=False)
    hash_appended: bool = field(metadata={"format": BoolFormat()})


@dataclass
class FirmwareImage(StructType):
    header: FirmwareImageFileHeader
    ext_header: FirmwareImageExtendedFileHeader
    first_segment_headers: tuple[int, int] = field(metadata={"format": SimpleFormat('2I')}, repr=False)
    app_desc: FirmwareAppDescription

    @classmethod
    def from_file(cls, file: BinaryIO) -> Self:
        result, data = cls.decode(file.read(FirmwareImage.get_min_size()))
        return result
