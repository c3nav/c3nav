from typing import Annotated, Union

from ninja import Schema
from pydantic import Field as APIField
from pydantic import NegativeInt, PositiveInt

from c3nav.api.utils import NonEmptyStr
from c3nav.routing.api.schemas import BSSIDSchema


class LocateRequestPeerSchema(Schema):
    bssid: BSSIDSchema = APIField(
        title="BSSID",
        description="BSSID of the peer",
        example="c3:42:13:37:ac:ab",
    )
    ssid: NonEmptyStr = APIField(
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
    distance: Union[
        float,
        Annotated[None, APIField(title="null", description="distance was not measured")]
    ] = APIField(
        default=None,
        title="distance",
        description="measured distance in meters",
        example=8.32
    )
