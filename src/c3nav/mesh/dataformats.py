import re
from dataclasses import dataclass, field
from enum import IntEnum, unique
from typing import Annotated, BinaryIO, Literal, Self

from annotated_types import Gt, Lt, MaxLen, Le
from pydantic import NegativeInt, PositiveInt
from pydantic_extra_types.mac_address import MacAddress

from c3nav.api.utils import EnumSchemaByNameMixin, TwoNibblesEncodable
from c3nav.mesh.baseformats import AsHex, FixedHexFormat, StructType, AsDefinition


class MacAddressFormat(FixedHexFormat):
    def __init__(self):
        super().__init__(num=6, sep=':')


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
    led_type: LedType = field(metadata={"c_name": "type"})


@dataclass
class NoLedConfig(LedConfig, led_type=LedType.NONE):
    pass


@dataclass
class SerialLedConfig(LedConfig, led_type=LedType.SERIAL):
    serial_led_type: SerialLedType = field(metadata={"c_name": "type"})
    gpio: Annotated[PositiveInt, Lt(2**8)]


@dataclass
class MultipinLedConfig(LedConfig, led_type=LedType.MULTIPIN):
    gpio_red: Annotated[PositiveInt, Lt(2**8)]
    gpio_green: Annotated[PositiveInt, Lt(2**8)]
    gpio_blue: Annotated[PositiveInt, Lt(2**8)]


@dataclass
class BoardSPIConfig(StructType):
    """
    configuration for spi bus used for ETH or UWB
    """
    gpio_miso: Annotated[PositiveInt, Lt(2**8)]
    gpio_mosi: Annotated[PositiveInt, Lt(2**8)]
    gpio_clk: Annotated[PositiveInt, Lt(2**8)]


@dataclass
class UWBConfig(StructType):
    """
    configuration for the connection to the UWB module
    """
    enable: bool
    gpio_cs: Annotated[PositiveInt, Lt(2**8)]
    gpio_irq: Annotated[PositiveInt, Lt(2**8)]
    gpio_rst: Annotated[PositiveInt, Lt(2**8)]
    gpio_wakeup: Annotated[PositiveInt, Lt(2**8)]
    gpio_exton: Annotated[PositiveInt, Lt(2**8)]


@dataclass
class UplinkEthConfig(StructType):
    """
    configuration for the connection to the ETH module
    """
    enable: bool
    gpio_cs: Annotated[PositiveInt, Lt(2**8)]
    gpio_int: Annotated[PositiveInt, Lt(2**8)]
    gpio_rst: Annotated[int, Gt(-1), Lt(2**7)]


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
    board: Annotated[BoardType, AsHex()] = field()  # todo: fix code so this field() isn't needed


@dataclass
class CustomBoardConfig(BoardConfig, board=BoardType.CUSTOM):
    spi: Annotated[BoardSPIConfig, AsDefinition()]
    uwb: Annotated[UWBConfig, AsDefinition()]
    eth: Annotated[UplinkEthConfig, AsDefinition()]
    led: Annotated[LedConfig, AsDefinition()]


@dataclass
class DevkitMBoardConfig(BoardConfig, board=BoardType.ESP32_C3_DEVKIT_M_1):
    spi: Annotated[BoardSPIConfig, AsDefinition()]
    uwb: Annotated[UWBConfig, AsDefinition()]
    eth: Annotated[UplinkEthConfig, AsDefinition()]


@dataclass
class Esp32SBoardConfig(BoardConfig, board=BoardType.ESP32_C3_32S):
    spi: Annotated[BoardSPIConfig, AsDefinition()]
    uwb: Annotated[UWBConfig, AsDefinition()]
    eth: Annotated[UplinkEthConfig, AsDefinition()]


@dataclass
class UwbBoardConfig(BoardConfig, board=BoardType.C3NAV_UWB_BOARD):
    eth: Annotated[UplinkEthConfig, AsDefinition()]


@dataclass
class LocationPCBRev0Dot1BoardConfig(BoardConfig, board=BoardType.C3NAV_LOCATION_PCB_REV_0_1):
    eth: Annotated[UplinkEthConfig, AsDefinition()]


@dataclass
class LocationPCBRev0Dot2BoardConfig(BoardConfig, board=BoardType.C3NAV_LOCATION_PCB_REV_0_2):
    eth: Annotated[UplinkEthConfig, AsDefinition()]


@dataclass
class RangeResultItem(StructType):
    peer: MacAddress
    rssi: Annotated[NegativeInt, Gt(-100)]
    distance: Annotated[int, Gt(-32000), Lt(32000)]


@dataclass
class RawFTMEntry(StructType):
    dlog_token: Annotated[PositiveInt, Lt(255)]
    rssi: Annotated[NegativeInt, Gt(-100)]
    rtt: Annotated[PositiveInt, Lt(2**32)]
    t1: Annotated[PositiveInt, Lt(2**64)]
    t2: Annotated[PositiveInt, Lt(2**64)]
    t3: Annotated[PositiveInt, Lt(2**64)]
    t4: Annotated[PositiveInt, Lt(2**64)]


@dataclass
class FirmwareAppDescription(StructType, existing_c_struct="esp_app_desc_t", c_includes=['<esp_app_desc.h>']):
    magic_word: Literal[0xAB_CD_54_32] = field(repr=False)
    secure_version: Annotated[PositiveInt, Lt(2**32)]
    reserv1: Annotated[bytes, MaxLen(8)] = field(repr=False)
    version: Annotated[str, MaxLen(32)]
    project_name: Annotated[str, MaxLen(32)]
    compile_time: Annotated[str, MaxLen(16)]
    compile_date: Annotated[str, MaxLen(16)]
    idf_version: Annotated[str, MaxLen(32)]
    app_elf_sha256: Annotated[str, MaxLen(32), AsHex()]
    reserv2: Annotated[bytes, MaxLen(20*4)] = field(repr=False)


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
class FlashSettings(TwoNibblesEncodable):
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
    magic_word: Literal[0xE9] = field(repr=False)
    num_segments: Annotated[PositiveInt, Lt(2**8)]
    spi_flash_mode: SPIFlashMode
    flash_stuff: FlashSettings
    entry_point: Annotated[PositiveInt, Lt(2**32)]


@dataclass
class FirmwareImageFileHeader(StructType):
    major: int
    minor: int
    num_segments: Annotated[PositiveInt, Lt(2**8)]
    spi_flash_mode: SPIFlashMode
    flash_stuff: FlashSettings
    entry_point: Annotated[PositiveInt, Lt(2**32)]


@dataclass
class FirmwareImageExtendedFileHeader(StructType):
    wp_pin: Annotated[PositiveInt, Lt(2**8)]
    drive_settings: Annotated[bytes, MaxLen(3)]
    chip: ChipType  # todo: 2 bytes
    min_chip_rev_old: int
    min_chip_rev: Annotated[PositiveInt, Le(9999)]
    max_chip_rev: Annotated[PositiveInt, Le(9999)]
    reserv: Annotated[bytes, MaxLen(4)] = field(repr=False)
    hash_appended: bool


@dataclass
class FirmwareImage(StructType):
    header: FirmwareImageFileHeader
    ext_header: FirmwareImageExtendedFileHeader
    first_segment_headers: Annotated[bytes, MaxLen(2)] = field(repr=False)  # todo: implement
    app_desc: FirmwareAppDescription

    @classmethod
    def from_file(cls, file: BinaryIO) -> Self:
        result, data = cls.decode(file.read(FirmwareImage.get_min_size()))
        return result
