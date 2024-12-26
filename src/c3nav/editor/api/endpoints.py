from django.urls import Resolver404, resolve
from django.utils.translation import gettext_lazy as _
from ninja import Router as APIRouter
from shapely.geometry.geo import mapping

from c3nav.api.auth import APIKeyAuth, auth_permission_responses
from c3nav.api.exceptions import API404
from c3nav.editor.api.base import api_etag_with_update_cache_key
from c3nav.editor.api.geometries import get_level_geometries_result, get_space_geometries_result
from c3nav.editor.api.schemas import EditorGeometriesElemSchema, EditorID, GeometryStylesSchema, UpdateCacheKey, \
    EditorBeaconsLookup
from c3nav.editor.views.base import editor_etag_func, accesses_mapdata
from c3nav.mapdata.api.base import api_etag
from c3nav.mapdata.models import Source
from c3nav.mapdata.schemas.responses import WithBoundsSchema
from c3nav.mesh.utils import get_nodes_and_ranging_beacons

editor_api_router = APIRouter(tags=["editor"], auth=APIKeyAuth(permissions={"editor_access"}))


@editor_api_router.get('/bounds/', summary="boundaries",
                       description="get maximum boundaries of everything on the map",
                       response={200: WithBoundsSchema, **auth_permission_responses},
                       openapi_extra={"security": [{"APIKeyAuth": ["editor_access"]}]})
@api_etag()
def bounds(request):
    return {
        "bounds": Source.max_bounds(),
    }


@editor_api_router.get('/geometrystyles/', summary="geometry styles",
                       description="get the default colors for each geometry type",
                       response={200: GeometryStylesSchema, **auth_permission_responses},
                       openapi_extra={"security": [{"APIKeyAuth": ["editor_access"]}]})
@api_etag(permissions=False)
def geometrystyles(request):
    return {
        'building': '#aaaaaa',
        'space': '#eeeeee',
        'hole': 'rgba(255, 0, 0, 0.3)',
        'door': '#ffffff',
        'area': '#55aaff',
        'stair': '#a000a0',
        'ramp': 'rgba(160, 0, 160, 0.2)',
        'obstacle': '#999999',
        'lineobstacle': '#999999',
        'column': 'rgba(0, 0, 50, 0.3)',
        'poi': '#4488cc',
        'shadow': '#000000',
        'graphnode': '#009900',
        'graphedge': '#00CC00',
        'altitudemarker': '#0000FF',
        'beaconmeasurement': '#DDDD00',
        'rangingbeacon': '#CC00CC',
        'dataoverlayfeature': '#3366ff',
    }


@editor_api_router.get('/geometries/space/{space_id}/', summary="space geometries",
                       description="get the geometries to display on the editor map for a space",
                       response={200: list[EditorGeometriesElemSchema], **API404.dict(),
                                 **auth_permission_responses},
                       openapi_extra={"security": [{"APIKeyAuth": ["editor_access"]}]})
@api_etag_with_update_cache_key(etag_func=editor_etag_func)
@accesses_mapdata
def space_geometries(request, space_id: EditorID, update_cache_key: UpdateCacheKey = None, **kwargs):
    # newapi_etag_with_update_cache_key does the following, don't let it confuse you:
    # - update_cache_key becomes the actual update_cache_key, not the one supplied be the user
    # - kwargs has "update_cache_key_match", which is true if update_cache_key matches the one supplied be the user
    # this is done so the api etag is correctly generated, as it takes the function arguments into account
    return get_space_geometries_result(
        request,
        space_id=space_id,
        update_cache_key=update_cache_key,
        update_cache_key_match=kwargs["update_cache_key_match"]
    )


@editor_api_router.get('/geometries/level/{level_id}/', summary="level geometries",
                       description="get the geometries to display on the editor map for a space",
                       response={200: list[EditorGeometriesElemSchema], **API404.dict(),
                                 **auth_permission_responses},
                       openapi_extra={"security": [{"APIKeyAuth": ["editor_access"]}]})
@api_etag_with_update_cache_key(etag_func=editor_etag_func)
@accesses_mapdata
def level_geometries(request, level_id: EditorID, update_cache_key: UpdateCacheKey = None, **kwargs):
    # newapi_etag_with_update_cache_key does the following, don't let it confuse you:
    # - update_cache_key becomes the actual update_cache_key, not the one supplied be the user
    # - kwargs has "update_cache_key_match", which is true if update_cache_key matches the one supplied be the user
    # this is done so the api etag is correctly generated, as it takes the function arguments into account
    return get_level_geometries_result(
        request,
        level_id=level_id,
        update_cache_key=update_cache_key,
        update_cache_key_match=kwargs["update_cache_key_match"]
    )


# todo: need a way to pass the changeset if it's not a session API key

def resolve_editor_path_api(request, path):
    resolved = None
    if path:
        try:
            resolved = resolve('/editor/'+path+'/')
        except Resolver404:
            pass

    if not resolved:
        try:
            resolved = resolve('/editor/'+path)
        except Resolver404:
            pass

    request.sub_resolver_match = resolved

    return resolved


@editor_api_router.get('/as_api/{path:path}', summary="raw editor access",
                       response={200: dict, **API404.dict(), **auth_permission_responses},
                       openapi_extra={"security": [{"APIKeyAuth": ["editor_access"]}]})
@api_etag()  # todo: correct?
def get_view_as_api(request, path: str):
    """
    get editor views rendered as JSON instead of HTML.
    `path` is the path after /editor/.
    this is a mess. good luck. if you actually want to use this, poke us so we might add better documentation.
    """
    resolved = resolve_editor_path_api(request, path)

    if not resolved:
        raise API404(_('No matching editor view endpoint found.'))

    if not getattr(resolved.func, 'api_hybrid', False):
        raise API404(_('Matching editor view point does not provide an API.'))

    response = resolved.func(request, api=True, *resolved.args, **resolved.kwargs)
    return response


@editor_api_router.post('/as_api/{path:path}', summary="raw editor access",
                        response={200: dict, **API404.dict(), **auth_permission_responses},
                        openapi_extra={"security": [{"APIKeyAuth": ["editor_access", "write"]}]})
@api_etag()  # todo: correct?
def post_view_as_api(request, path: str):
    """
    get editor views rendered as JSON instead of HTML.
    `path` is the path after /editor/.
    this is a mess. good luck. if you actually want to use this, poke us so we might add better documentation.
    """
    raise NotImplementedError


@editor_api_router.get('/beacons-lookup/', summary="get beacon coordinates",
                       description="get xyz coordinates for all known positioning beacons",
                       response={200: EditorBeaconsLookup, **auth_permission_responses},
                       openapi_extra={"security": [{"APIKeyAuth": ["editor_access", "write"]}]})
def beacons_lookup(request):
    # todo: update with more details? todo permission?
    from c3nav.mesh.messages import MeshMessageType
    calculated = get_nodes_and_ranging_beacons()

    wifi_beacons = {}
    ibeacons = {}
    for beacon in calculated.beacons.values():
        node = calculated.nodes_for_beacons.get(beacon.id, None)
        beacon_data = {
            "name": node.name if node else ("Beacon #%d" % beacon.pk),
            "point": mapping(beacon.geometry),
        }
        for bssid in beacon.wifi_bssids:
            wifi_beacons[bssid] = beacon_data
        if beacon.ibeacon_uuid and beacon.ibeacon_major is not None and beacon.ibeacon_minor is not None:
            ibeacons.setdefault(
                str(beacon.ibeacon_uuid), {}
            ).setdefault(
                beacon.ibeacon_major, {}
            )[beacon.ibeacon_minor] = beacon_data

    for node in calculated.nodes.values():
        beacon_data = {
            "name": node.name,
            "point": None,
        }
        ibeacon_msg = node.last_messages[MeshMessageType.CONFIG_IBEACON]
        if ibeacon_msg:
            ibeacons.setdefault(
                str(ibeacon_msg.parsed.content.uuid), {}
            ).setdefault(
                ibeacon_msg.parsed.content.major, {}
            ).setdefault(
                ibeacon_msg.parsed.content.minor, beacon_data
            )

        node_msg = node.last_messages[MeshMessageType.CONFIG_NODE]
        if node_msg:
            wifi_beacons.setdefault(node.address, beacon_data)

    return EditorBeaconsLookup(
        wifi_beacons=wifi_beacons,
        ibeacons=ibeacons,
    ).model_dump(mode="json")