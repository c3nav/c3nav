import json
from typing import Optional

from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.shortcuts import redirect
from django.utils import timezone
from ninja import Query
from ninja import Router as APIRouter
from ninja import Schema
from pydantic import Field as APIField

from c3nav.api.exceptions import API404, APIPermissionDenied, APIRequestValidationFailed
from c3nav.api.newauth import auth_permission_responses, auth_responses, validate_responses
from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.models import Source
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.models.locations import DynamicLocation, LocationRedirect, Position
from c3nav.mapdata.newapi.base import newapi_etag, newapi_stats
from c3nav.mapdata.schemas.filters import BySearchableFilter, RemoveGeometryFilter
from c3nav.mapdata.schemas.model_base import AnyLocationID, AnyPositionID, CustomLocationID
from c3nav.mapdata.schemas.models import (AnyPositionStatusSchema, FullListableLocationSchema, FullLocationSchema,
                                          LocationDisplay, SlimListableLocationSchema, SlimLocationSchema)
from c3nav.mapdata.schemas.responses import BoundsSchema, LocationGeometry
from c3nav.mapdata.utils.locations import (get_location_by_id_for_request, get_location_by_slug_for_request,
                                           searchable_locations_for_request, visible_locations_for_request)
from c3nav.mapdata.utils.user import can_access_editor

map_api_router = APIRouter(tags=["map"])


@map_api_router.get('/bounds/', summary="Get map boundaries",
                    response={200: BoundsSchema, **auth_responses})
@newapi_etag(permissions=False)
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
    if filters.searchable:
        locations = searchable_locations_for_request(request)
    else:
        locations = visible_locations_for_request(request).values()

    result = tuple(obj.serialize(detailed=detailed, search=filters.searchable,
                                 geometry=filters.geometry and can_access_geometry(request),
                                 simple_geometry=True)
                   for obj in locations)
    return result


@map_api_router.get('/locations/',
                    response={200: list[SlimListableLocationSchema], **validate_responses, **auth_responses},
                    summary="Get locations (with most important attributes)")
@newapi_etag(base_mapdata=True)
def location_list(request, filters: Query[LocationListFilters]):
    return _location_list(request, detailed=False, filters=filters)


@map_api_router.get('/locations/full/',
                    response={200: list[FullListableLocationSchema], **validate_responses, **auth_responses},
                    summary="Get locations (with all attributes)")
@newapi_etag(base_mapdata=True)
def location_list_full(request, filters: Query[LocationListFilters]):
    return _location_list(request, detailed=True, filters=filters)


def _location_retrieve(request, location, detailed: bool, geometry: bool, show_redirects: bool):
    # todo: cache, visibility, etc…

    if location is None:
        raise API404()

    if isinstance(location, LocationRedirect):
        if not show_redirects:
            return redirect('../' + str(location.target.slug))  # todo: use reverse, make pk and slug both work

    if isinstance(location, (DynamicLocation, Position)):
        request._target_etag = None
        request._target_cache_key = None

    return location.serialize(
        detailed=detailed,
        geometry=geometry and can_access_geometry(request),
        simple_geometry=True
    )


def _location_display(request, location):
    # todo: cache, visibility, etc…

    if location is None:
        raise API404()

    if isinstance(location, LocationRedirect):
        return redirect('../' + str(location.target.slug) + '/details/')  # todo: use reverse, make pk+slug work

    result = location.details_display(
        detailed_geometry=can_access_geometry(request),
        editor_url=can_access_editor(request)
    )
    from pprint import pprint
    pprint(result)
    return json.loads(json.dumps(result, cls=DjangoJSONEncoder))  # todo: wtf?? well we need to get rid of lazy strings


def _location_geometry(request, location):
    # todo: cache, visibility, etc…

    if location is None:
        raise API404()

    if isinstance(location, LocationRedirect):
        return redirect('../' + str(location.target.slug) + '/geometry/')  # todo: use reverse, make pk+slug work

    return LocationGeometry(
        id=location.pk,
        level=getattr(location, 'level_id', None),
        geometry=location.get_geometry(
            detailed_geometry=can_access_geometry(request)
        )
    )


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
@newapi_stats('location_get')
@newapi_etag(base_mapdata=True)
def location_by_id(request, location_id: AnyLocationID, filters: Query[RemoveGeometryFilter],
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
@newapi_stats('location_get')
@newapi_etag(base_mapdata=True)
def location_by_id_full(request, location_id: AnyLocationID, filters: Query[RemoveGeometryFilter],
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
@newapi_stats('location_display')
@newapi_etag(base_mapdata=True)
def location_by_id_display(request, location_id: AnyLocationID):
    return _location_display(
        request,
        get_location_by_id_for_request(location_id, request),
    )


@map_api_router.get('/locations/{location_id}/geometry/',
                    response={200: LocationGeometry, **API404.dict(), **auth_responses},
                    summary="Get location geometry (if available) by ID",
                    description="a numeric ID for a map location or a string ID for generated locations can be used")
@newapi_stats('location_geometery')
@newapi_etag(base_mapdata=True)
def location_by_id_geometry(request, location_id: AnyLocationID):
    return _location_geometry(
        request,
        get_location_by_id_for_request(location_id, request),
    )


@map_api_router.get('/locations/by-slug/{location_slug}/',
                    response={200: SlimLocationSchema, **API404.dict(), **validate_responses, **auth_responses},
                    summary="Get location by slug (with most important attributes)")
@newapi_stats('location_get')
@newapi_etag(base_mapdata=True)
def location_by_slug(request, location_slug: NonEmptyStr, filters: Query[RemoveGeometryFilter],
                     redirects: Query[ShowRedirects]):
    return _location_retrieve(
        request,
        get_location_by_slug_for_request(location_slug, request),
        detailed=False, geometry=filters.geometry, show_redirects=redirects.show_redirects,
    )


@map_api_router.get('/locations/by-slug/{location_slug}/full/',
                    response={200: FullLocationSchema, **API404.dict(), **validate_responses, **auth_responses},
                    summary="Get location by slug (with all attributes)")
@newapi_stats('location_get')
@newapi_etag(base_mapdata=True)
def location_by_slug_full(request, location_slug: NonEmptyStr, filters: Query[RemoveGeometryFilter],
                          redirects: Query[ShowRedirects]):
    return _location_retrieve(
        request,
        get_location_by_slug_for_request(location_slug, request),
        detailed=True, geometry=filters.geometry, show_redirects=redirects.show_redirects,
    )


@map_api_router.get('/locations/by-slug/{location_slug}/display/',
                    response={200: LocationDisplay, **API404.dict(), **auth_responses},
                    summary="Get location display data by slug")
@newapi_stats('location_display')
@newapi_etag(base_mapdata=True)
def location_by_slug_display(request, location_slug: NonEmptyStr):
    return _location_display(
        request,
        get_location_by_slug_for_request(location_slug, request),
    )


@map_api_router.get('/locations/by-slug/{location_slug}/geometry/',
                    response={200: LocationGeometry, **API404.dict(), **auth_responses},
                    summary="Get location geometry (if available) by slug")
@newapi_stats('location_geometry')
@newapi_etag(base_mapdata=True)
def location_by_slug_geometry(request, location_slug: NonEmptyStr):
    return _location_geometry(
        request,
        get_location_by_slug_for_request(location_slug, request),
    )


@map_api_router.get('/get_position/{position_id}/',
                    response={200: AnyPositionStatusSchema, **API404.dict(), **auth_responses},
                    summary="get coordinates of a moving position",
                    description="a numeric ID for a dynamic location or a string ID for the position secret can be used")
@newapi_stats('get_position')
def get_current_position_by_id(request, position_id: AnyPositionID):
    # no caching for obvious reasons!
    location = None
    if isinstance(position_id, int) or position_id.isdigit():
        location = get_location_by_id_for_request(position_id, request)
        if not isinstance(location, DynamicLocation):
            raise API404()
    if location is None and position_id.startswith('p:'):
        try:
            location = Position.objects.get(secret=position_id[2:])
        except Position.DoesNotExist:
            raise API404()
    return location.serialize_position()


class UpdatePositionSchema(Schema):
    coordinates_id: Optional[CustomLocationID] = APIField(
        description="coordinates to set the location to or None to unset it"
    )
    timeout: Optional[int] = APIField(
        None,
        description="timeout for this new location in seconds, or None if not to change it",
        example=None,
    )


@map_api_router.put('/get_position/{position_id}/', url_name="position-update",
                    response={200: AnyPositionStatusSchema, **API404.dict(), **auth_permission_responses},
                    summary="set coordinates of a moving position",
                    description="only the string ID for the position secret must be used")
@newapi_stats('get_position')
def position_update(request, position_id: AnyPositionID, update: UpdatePositionSchema):
    # todo: may an API key do this?
    if not update.position_id.startswith('p:'):
        raise API404()
    try:
        location = Position.objects.get(secret=update.position_id[2:])
    except Position.DoesNotExist:
        raise API404()
    if location.owner != request.user:
        raise APIPermissionDenied()

    coordinates = get_location_by_id_for_request(update.coordinates_id, request)
    if coordinates is None:
        raise APIRequestValidationFailed('Cant resolve coordinates.')

    location.coordinates_id = update.coordinates_id
    location.timeout = update.timeout
    location.last_coordinates_update = timezone.now()
    location.save()

    return location.serialize_position()
