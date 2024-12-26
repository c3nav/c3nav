from typing import Annotated, Union, Optional
from uuid import UUID

from annotated_types import Lt
from pydantic import Field as APIField
from pydantic import NegativeInt, PositiveInt
from pydantic.types import NonNegativeInt, NonNegativeFloat
from pydantic_extra_types.mac_address import MacAddress

from c3nav.api.schema import BaseSchema


class WifiPeerInformationElement(BaseSchema):
    id: PositiveInt
    id_ext: PositiveInt
    data: Annotated[list[Annotated[NonNegativeInt, Lt(2**8)]], APIField(description="list of bytes")]


class LocateWifiPeerSchema(BaseSchema):
    bssid: MacAddress = APIField(
        title="BSSID",
        description="BSSID of the peer",
        example="c3:42:13:37:ac:ab",
    )
    ssid: str = APIField(
        title="SSID",
        description="(E)SSID of the peer",
        example="c3nav-locate",
    )
    rssi: NegativeInt = APIField(
        title="RSSI",
        description="RSSI in dBm",
        example=-42,
    )
    frequency: Union[
        PositiveInt,
        Annotated[None, APIField(title="null", description="frequency not given")]
    ] = APIField(
        default=None,
        title="frequency",
        description="frequency in KHz",
        example=2472,
    )
    supports80211mc: Union[
        bool,
        Annotated[None, APIField(title="null", description="802.11mc support was not determined")]
    ] = APIField(
        default=None,
        title="supports80211mc",
        description="access point supports 802.11mc",
        example=True
    )
    distance: Union[
        float,
        Annotated[None, APIField(title="null", description="distance was not measured")]
    ] = APIField(
        default=None,
        title="distance",
        description="measured distance in meters",
        example=8.32
    )
    distance_sd: Union[
        float,
        Annotated[None, APIField(title="null", description="distance standard deviation not available")]
    ] = APIField(
        default=None,
        title="distance standard deviation",
        description="standard deviation of measurements in meters",
        example=1.23
    )
    info_elems: list[WifiPeerInformationElement] = APIField(
        default=[],
        title="information elements / vendor data",
        description="if avaiilable",
    )


class LocateIBeaconPeerSchema(BaseSchema):
    uuid: UUID = APIField(
        title="UUID",
        description="UUID of the iBeacon",
        example="a142621a-2f42-09b3-245b-e1ac6356e9b0",
    )
    major: Annotated[NonNegativeInt, Lt(2 ** 16)] = APIField(
        title="major value of the iBeacon",
    )
    minor: Annotated[NonNegativeInt, Lt(2 ** 16)] = APIField(
        title="minor value of the iBeacon",
    )
    distance: Optional[NonNegativeFloat] = APIField(
        default=None,
        title="determined iBeacon distance in meters",
    )
    last_seen_ago: Optional[NonNegativeInt ]= APIField(
        default=None,
        title="how many milliseconds ago this beacon was last seen"
    )


class BeaconMeasurementDataSchema(BaseSchema):
    wifi: list[list[LocateWifiPeerSchema]] = []
    ibeacon: list[list[LocateIBeaconPeerSchema]] = []