from typing import Annotated, Union

from pydantic import Field as APIField
from pydantic import NegativeInt, PositiveInt

from c3nav.api.schema import BaseSchema
from c3nav.api.utils import NonEmptyStr

BSSIDSchema = Annotated[str, APIField(pattern=r"^[a-z0-9]{2}(:[a-z0-9]{2}){5}$", title="BSSID")]


class LocateRequestPeerSchema(BaseSchema):
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
