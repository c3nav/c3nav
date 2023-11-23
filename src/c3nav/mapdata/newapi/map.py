import json
from typing import Annotated, Union

from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.shortcuts import redirect
from ninja import Query
from ninja import Router as APIRouter
from ninja import Schema
from pydantic import Field as APIField
from pydantic import PositiveInt

from c3nav.api.exceptions import API404
from c3nav.api.newauth import auth_responses, validate_responses
from c3nav.mapdata.models import Source
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.models.locations import LocationRedirect
from c3nav.mapdata.schemas.filters import BySearchableFilter, RemoveGeometryFilter
from c3nav.mapdata.schemas.model_base import LocationID
from c3nav.mapdata.schemas.models import FullLocationSchema, LocationDisplay, SlimLocationSchema
from c3nav.mapdata.schemas.responses import BoundsSchema
from c3nav.mapdata.utils.locations import (get_location_by_id_for_request, searchable_locations_for_request,
                                           visible_locations_for_request)
from c3nav.mapdata.utils.user import can_access_editor

map_api_router = APIRouter(tags=["map"])


@map_api_router.get('/bounds/', summary="Get map boundaries",
                    response={200: BoundsSchema, **auth_responses})
def bounds(request):
    return {
        "bounds": Source.max_bounds(),
    }


class LocationEndpointParameters(Schema):
    searchable: bool = APIField(
        False,
        title='only list searchable locations',
        description='if set, only searchable locations will be listed'
    )


def can_access_geometry(request):
    return True  # todo: implementFd


class LocationListFilters(BySearchableFilter, RemoveGeometryFilter):
    pass


def _location_list(request, detailed: bool, filters: LocationListFilters):
    # todo: cache, visibility, etc…
    cache_key = 'mapdata:api:location:list:%d:%s:%d' % (
        filters.searchable + detailed*2 + filters.geometry*4,
        AccessPermission.cache_key_for_request(request),
        request.user_permissions.can_access_base_mapdata
    )
    result = cache.get(cache_key, None)
    if result is None:
        if filters.searchable:
            locations = searchable_locations_for_request(request)
        else:
            locations = visible_locations_for_request(request).values()

        result = tuple(obj.serialize(detailed=detailed, search=filters.searchable,
                                     geometry=filters.geometry and can_access_geometry(request),
                                     simple_geometry=True)
                       for obj in locations)
        cache.set(cache_key, result, 300)
    return result


@map_api_router.get('/locations/',
                    response={200: list[SlimLocationSchema], **validate_responses, **auth_responses},
                    summary="Get locations (with most important attributes)")
def location_list(request, filters: Query[LocationListFilters]):
    return _location_list(request, detailed=False, filters=filters)


@map_api_router.get('/locations/full/',
                    response={200: list[FullLocationSchema], **validate_responses, **auth_responses},
                    summary="Get locations (with all attributes)")
def location_list_full(request, filters: Query[LocationListFilters]):
    return _location_list(request, detailed=True, filters=filters)


def _location_retrieve(request, location, detailed: bool, geometry: bool, show_redirects: bool):
    # todo: cache, visibility, etc…

    if location is None:
        raise API404

    if isinstance(location, LocationRedirect):
        if not show_redirects:
            return redirect('../' + str(location.target.slug))  # todo: use reverse, make pk and slug both work

    return location.serialize(
        detailed=detailed,
        geometry=geometry and can_access_geometry(request),
        simple_geometry=True
    )


def _location_display(request, location):
    # todo: cache, visibility, etc…

    if location is None:
        raise API404

    if isinstance(location, LocationRedirect):
        return redirect('../' + str(location.target.slug) + '/details/')  # todo: use reverse, make pk+slug work

    result = location.details_display(
        detailed_geometry=can_access_geometry(request),
        editor_url=can_access_editor(request)
    )
    from pprint import pprint
    pprint(result)
    return json.loads(json.dumps(result, cls=DjangoJSONEncoder))  # todo: wtf?? well we need to get rid of lazy strings


class ShowRedirects(Schema):
    show_redirects: bool = APIField(
        False,
        name="show redirects",
        description="whether to show redirects instead of sending a redirect response",
    )


@map_api_router.get('/locations/{location_id}/',
                    response={200: SlimLocationSchema, **API404.dict(), **validate_responses, **auth_responses},
                    summary="Get location by ID (with most important attributes)",
                    description="a numeric ID for a map location or a string ID for generated locations can be used")
def location_by_id(request, location_id: LocationID, filters: Query[RemoveGeometryFilter],
                      redirects: Query[ShowRedirects]):
    return _location_retrieve(
        request,
        get_location_by_id_for_request(location_id, request),
        detailed=False, geometry=filters.geometry, show_redirects=redirects.show_redirects,
    )


@map_api_router.get('/locations/{location_id}/full/',
                    response={200: FullLocationSchema, **API404.dict(), **validate_responses, **auth_responses},
                    summary="Get location by ID (with all attributes)",
                    description="a numeric ID for a map location or a string ID for generated locations can be used")
def location_by_id_full(request, location_id: LocationID, filters: Query[RemoveGeometryFilter],
                           redirects: Query[ShowRedirects]):
    return _location_retrieve(
        request,
        get_location_by_id_for_request(location_id, request),
        detailed=True, geometry=filters.geometry, show_redirects=redirects.show_redirects,
    )


@map_api_router.get('/locations/{location_id}/display/',
                    response={200: LocationDisplay, **API404.dict(), **auth_responses},
                    summary="Get location display data by ID",
                    description="a numeric ID for a map location or a string ID for generated locations can be used")
def location_by_id_display(request, location_id: LocationID):
    return _location_display(
        request,
        get_location_by_id_for_request(location_id, request),
    )


