from typing import Annotated

from ninja import Field as APIField
from ninja import Router as APIRouter

from c3nav.api.newauth import auth_responses
from c3nav.mapdata.models import Source
from c3nav.mapdata.schemas.responses import BoundsSchema
from c3nav.routing.rangelocator import RangeLocator

positioning_api_router = APIRouter(tags=["positioning"])


@positioning_api_router.post('/locate/', summary="locate based on wifi scans",
                             response={200: BoundsSchema, **auth_responses})
def locate(request):
    # todo: implement
    return {
        "bounds": Source.max_bounds(),
    }


@positioning_api_router.get('/locate-test/', summary="get dummy location for debugging",
                            response={200: BoundsSchema, **auth_responses})
def locate_test(request):
    # todo: implement
    return {
        "bounds": Source.max_bounds(),
    }


BeaconsXYZ = dict[
    Annotated[str, APIField(pattern=r"^[a-z0-9]{2}(:[a-z0-9]{2}){5}$", title="BSSID")],
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
def beacons_xyz(request):
    return RangeLocator.load().get_all_xyz()
