from ninja import Router as APIRouter

from c3nav.api.exceptions import API404
from c3nav.api.newauth import APITokenAuth, auth_permission_responses
from c3nav.editor.newapi.base import newapi_etag_with_update_cache_key
from c3nav.editor.newapi.geometries import get_level_geometries_result, get_space_geometries_result
from c3nav.editor.newapi.schemas import (EditorID, EditorLevelGeometriesElemSchema, EditorSpaceGeometriesElemSchema,
                                         GeometryStylesSchema, UpdateCacheKey)
from c3nav.editor.views.base import editor_etag_func
from c3nav.mapdata.models import Source
from c3nav.mapdata.newapi.base import newapi_etag
from c3nav.mapdata.schemas.responses import BoundsSchema

editor_api_router = APIRouter(tags=["editor"], auth=APITokenAuth(permissions={"editor_access"}))


@editor_api_router.get('/bounds/', summary="Get editor map boundaries",
                       response={200: BoundsSchema, **auth_permission_responses},
                       openapi_extra={"security": [{"APITokenAuth": ["editor_access"]}]})
@newapi_etag()
def bounds():
    return {
        "bounds": Source.max_bounds(),
    }


@editor_api_router.get('/geometrystyles/', summary="get the default colors for each geometry type",
                       response={200: GeometryStylesSchema, **auth_permission_responses},
                       openapi_extra={"security": [{"APITokenAuth": ["editor_access"]}]})
@newapi_etag(permissions=False)
def geometrystyles():
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
        'wifimeasurement': '#DDDD00',
        'rangingbeacon': '#CC00CC',
    }


@editor_api_router.get('/geometries/space/{space_id}/', summary="get the geometries to display for a space",
                       response={200: list[EditorSpaceGeometriesElemSchema], **API404.dict(),
                                 **auth_permission_responses},
                       openapi_extra={"security": [{"APITokenAuth": ["editor_access"]}]})
@newapi_etag_with_update_cache_key(etag_func=editor_etag_func)  # todo: correct?
def space_geometries(request, space_id: EditorID, update_cache_key: UpdateCacheKey = None, **kwargs):
    """
    look. this is a complex mess. there will hopefully be more documentation soon. or a better endpoint.
    """
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
    # todo: test the heck out of this


@editor_api_router.get('/geometries/level/{level_id}/', summary="get the geometries to display for a level",
                       response={200: list[EditorLevelGeometriesElemSchema], **API404.dict(),
                                 **auth_permission_responses},
                       openapi_extra={"security": [{"APITokenAuth": ["editor_access"]}]})
@newapi_etag()  # todo: correct?
def level_geometries(request, level_id: EditorID, update_cache_key: UpdateCacheKey = None, **kwargs):
    """
    look. this is a complex mess. there will hopefully be more documentation soon. or a better endpoint.
    """
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
    # todo: test the heck out of this


# todo: need a way to pass the changeset if it's not a session API key


@editor_api_router.get('/{path:path}/', summary="access the editor UI programmatically",
                       response={200: dict, **API404.dict(), **auth_permission_responses},
                       openapi_extra={"security": [{"APITokenAuth": ["editor_access"]}]})
@newapi_etag()  # todo: correct?
def view_as_api(path: str):
    """
    get editor views rendered as JSON instead of HTML.
    `path` is the path after /editor/.
    this is a mess. good luck. if you actually want to use this, poke us so we might add better documentation.
    """

    raise NotImplementedError


@editor_api_router.post('/{path:path}/', summary="access the editor UI programmatically",
                        response={200: dict, **API404.dict(), **auth_permission_responses},
                        openapi_extra={"security": [{"APITokenAuth": ["editor_access", "write"]}]})
@newapi_etag()  # todo: correct?
def view_as_api(path: str):
    """
    get editor views rendered as JSON instead of HTML.
    `path` is the path after /editor/.
    this is a mess. good luck. if you actually want to use this, poke us so we might add better documentation.
    """
    raise NotImplementedError
