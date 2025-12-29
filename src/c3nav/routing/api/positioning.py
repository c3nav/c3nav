from typing import Annotated, Union

from django.conf import settings
from django.core.exceptions import ValidationError
from ninja import Field as APIField
from ninja import Router as APIRouter
from pydantic import PositiveFloat
from pydantic_extra_types.mac_address import MacAddress

from c3nav.api.auth import auth_responses
from c3nav.api.schema import BaseSchema
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.models.geometry.space import AutoBeaconMeasurement
from c3nav.mapdata.schemas.models import CustomLocationSchema
from c3nav.mapdata.tasks import update_ap_names_bssid_mapping
from c3nav.mapdata.utils.cache.stats import increment_cache_key
from c3nav.routing.locator import Locator
from c3nav.routing.schemas import LocateWifiPeerSchema, LocateIBeaconPeerSchema, BeaconMeasurementDataSchema, \
    RangePeerSchema

positioning_api_router = APIRouter(tags=["positioning"])


class LocateRequestSchema(BaseSchema):
    wifi_peers: list[LocateWifiPeerSchema] = APIField(
        title="list of visible/measured wifi location beacons",
    )
    ibeacon_peers: list[LocateIBeaconPeerSchema] = APIField(
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
    precision: Union[
        Annotated[PositiveFloat, APIField(title="precision")],
        Annotated[None, APIField(title="null", description="precision unknown or not applicable")]
    ] = APIField(
        title="precision",
        description="estimated description in meters",
    )
    suggested_peers: list[RangePeerSchema] = APIField(
        title="suggested peers",
        description="suggested peers to range, in descending priority",
    )


@positioning_api_router.post('/locate/', summary="determine position",
                             description="determine position based on wireless measurements "
                                         "(including ranging, if available)",
                             response={200: PositioningResult, **auth_responses})
def get_position(request, parameters: LocateRequestSchema):
    try:
        located = Locator.load().locate(parameters.wifi_peers,
                                        permissions=AccessPermission.get_for_request(request), stats=True)
        location = located.location
        if location is not None:
            increment_cache_key('apistats__locate_%s' % location.rounded_pk)
    except ValidationError:
        # todo: validation error, seriously? this shouldn't happen anyways
        raise

    if request.user_permissions.passive_ap_name_scanning:
        bssid_mapping = {}
        for peer in parameters.wifi_peers:
            if not peer.ap_name:
                continue
            bssid_mapping.setdefault(peer.ap_name, set()).add(peer.bssid)
        if bssid_mapping:
            update_ap_names_bssid_mapping.delay(
                map_name={str(name): [str(b) for b in bssids] for name, bssids in bssid_mapping.items()},
                user_id=request.user.pk
            )

    if request.user_permissions.passive_scan_collection:
        AutoBeaconMeasurement.objects.create(
            author=request.user,
            data=BeaconMeasurementDataSchema(
                wifi=[parameters.wifi_peers],
                ibeacon=[parameters.ibeacon_peers],
            )
        )

    return {
        "location": location,
        "suggested_peers": located.suggested_peers,
        "precision": located.precision,
    }


if settings.METRICS:
    from c3nav.mapdata.metrics import APIStatsCollector
    APIStatsCollector.add_stat('locate', ['location'])
    APIStatsCollector.add_stat('locatemethod', ['method'])
    APIStatsCollector.add_stat('locaterangepeers', ['peers'])


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
        "location": location
    }


BeaconsXYZ = dict[
    MacAddress,
    Annotated[
        tuple[
            Annotated[int, APIField(title="X (in cm)")],
            Annotated[int, APIField(title="Y (in cm)")],
            Annotated[int, APIField(title="Z (in cm)")],
        ],
        APIField(title="global XYZ coordinates")
    ]
]