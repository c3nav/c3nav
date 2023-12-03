from typing import Annotated, Optional

from ninja import Field as APIField
from ninja import Router as APIRouter
from ninja import Schema
from pydantic import NegativeInt

from c3nav.api.newauth import auth_responses
from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.models import Source
from c3nav.mapdata.schemas.models import CustomLocationSchema
from c3nav.mapdata.schemas.responses import BoundsSchema
from c3nav.routing.rangelocator import RangeLocator

BSSIDSchema = Annotated[str, APIField(pattern=r"^[a-z0-9]{2}(:[a-z0-9]{2}){5}$", title="BSSID")]

positioning_api_router = APIRouter(tags=["positioning"])


class LocateRequestItemSchema(Schema):
    ssid: NonEmptyStr
    bssid: BSSIDSchema
    rssi: NegativeInt
    distance: Optional[float] = None


class LocateRequestSchema(Schema):
    items: list[LocateRequestItemSchema]


class PositioningResult(Schema):
    location: Optional[CustomLocationSchema]


@positioning_api_router.post('/locate/', summary="locate based on wifi scans",
                             response={200: PositioningResult, **auth_responses})
def locate(locate_data: LocateRequestSchema):
    # todo: implement
    raise NotImplementedError


@positioning_api_router.get('/locate-test/', summary="get dummy location for debugging",
                            response={200: PositioningResult, **auth_responses})
def locate_test():
    raise NotImplementedError


BeaconsXYZ = dict[
    BSSIDSchema,
    Annotated[
        tuple[
            Annotated[int, APIField(title="X (in cm)")],
            Annotated[int, APIField(title="Y (in cm)")],
            Annotated[int, APIField(title="Z (in cm)")],
        ],
        APIField(title="global XYZ coordinates")
    ]
]


@positioning_api_router.get('/beacons-xyz/', summary="get calculated x y z for all beacons",
                            response={200: BeaconsXYZ, **auth_responses})
def beacons_xyz():
    return RangeLocator.load().get_all_xyz()
