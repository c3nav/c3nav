from typing import Annotated, Union

from django.core.exceptions import ValidationError
from ninja import Field as APIField
from ninja import Router as APIRouter
from ninja import Schema
from pydantic import NegativeInt, PositiveInt

from c3nav.api.auth import auth_responses
from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.schemas.models import CustomLocationSchema
from c3nav.mapdata.utils.cache.stats import increment_cache_key
from c3nav.routing.locator import Locator
from c3nav.routing.rangelocator import RangeLocator

BSSIDSchema = Annotated[str, APIField(pattern=r"^[a-z0-9]{2}(:[a-z0-9]{2}){5}$", title="BSSID")]

positioning_api_router = APIRouter(tags=["positioning"])


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


class LocateRequestSchema(Schema):
    peers: list[LocateRequestPeerSchema] = APIField(
        title="list of visible/measured location beacons",
    )


class PositioningResult(Schema):
    location: Union[
        Annotated[CustomLocationSchema, APIField(title="location")],
        Annotated[None, APIField(title="null", description="position could not be determined")]
    ] = APIField(
        title="location",
        description="positinoing result",
    )


@positioning_api_router.post('/locate/', summary="determine position",
                             description="determine position based on wireless measurements "
                                         "(including ranging, if available)",
                             response={200: PositioningResult, **auth_responses})
def get_position(request, parameters: LocateRequestSchema):
    try:
        location = Locator.load().locate(parameters.dict()["peers"], permissions=AccessPermission.get_for_request(request))
        if location is not None:
            # todo: this will overload us probably, group these
            increment_cache_key('apistats__locate__%s' % location.pk)
    except ValidationError:
        # todo: validation error, seriously? this shouldn't happen anyways
        raise

    return {
        "location": location.serialize(simple_geometry=True),
    }


@positioning_api_router.get('/locate-test/', summary="debug position",
                            description="outputs a location for debugging purposes",
                            response={200: PositioningResult, **auth_responses})
def locate_test():
    from c3nav.mesh.messages import MeshMessageType
    from c3nav.mesh.models import MeshNode
    try:
        node = MeshNode.objects.prefetch_last_messages(MeshMessageType.LOCATE_RANGE_RESULTS).get(
            address="d4:f9:8d:2d:0d:f1"
        )
    except MeshNode.DoesNotExist:
        return {
            "location": None
        }
    msg = node.last_messages[MeshMessageType.LOCATE_RANGE_RESULTS]

    locator = RangeLocator.load()
    location = locator.locate(
        {
            r.peer: r.distance
            for r in msg.parsed.ranges
            if r.distance != 0xFFFF
        },
        None
    )
    return {
        "ranges": msg.parsed.tojson(msg.parsed)["ranges"],
        "datetime": msg.datetime,
        "location": location.serialize(simple_geometry=True) if location else None
    }


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


@positioning_api_router.get('/beacons-xyz/', summary="get beacon coordinates",
                            description="get xyz coordinates for all known positioning beacons",
                            response={200: BeaconsXYZ, **auth_responses})
def beacons_xyz():
    return RangeLocator.load().get_all_xyz()
