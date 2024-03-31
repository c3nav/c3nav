from typing import Annotated, Union

from django.conf import settings
from django.core.exceptions import ValidationError
from ninja import Field as APIField
from ninja import Router as APIRouter

from c3nav.api.auth import auth_responses
from c3nav.api.schema import BaseSchema
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.schemas.models import CustomLocationSchema
from c3nav.mapdata.utils.cache.stats import increment_cache_key
from c3nav.routing.locator import Locator
from c3nav.routing.schemas import BSSIDSchema, LocateRequestWifiPeerSchema, LocateRequestIBeaconPeerSchema

positioning_api_router = APIRouter(tags=["positioning"])


class LocateRequestSchema(BaseSchema):
    wifi_peers: list[LocateRequestWifiPeerSchema] = APIField(
        title="list of visible/measured wifi location beacons",
    )
    ibeacon_peers: list[LocateRequestIBeaconPeerSchema] = APIField(
        title="list of visible/measured location iBeacons",
    )


class PositioningResult(BaseSchema):
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
        location = Locator.load().locate(parameters.dict()["peers"],
                                         permissions=AccessPermission.get_for_request(request))
        if location is not None:
            # todo: this will overload us probably, group these
            increment_cache_key('apistats__locate__%s' % location.pk)
    except ValidationError:
        # todo: validation error, seriously? this shouldn't happen anyways
        raise

    return {
        "location": location.serialize(simple_geometry=True) if location else None,
    }


if settings.METRICS:
    from c3nav.mapdata.metrics import APIStatsCollector
    APIStatsCollector.add_stat('locate', 'location')


@positioning_api_router.get('/locate-test/', summary="debug position",
                            description="outputs a location for debugging purposes",
                            response={200: PositioningResult, **auth_responses})
def locate_test(request):
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

    locator = Locator.load()
    location = locator.locate_range(
        locator.convert_raw_scan_data([
            {
                "bssid": r.peer,
                "ssid": "",
                "rssi": r.rssi,
                "distance": r.distance,
            }
            for r in msg.parsed.ranges
            if r.distance != 0xFFFF
        ]),
        None
    )
    return {
        "ranges": msg.parsed.model_dump(mode="json")["ranges"],
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
    return Locator.load().get_all_xyz()
