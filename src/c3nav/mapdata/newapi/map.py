from django.core.cache import cache
from ninja import Query
from ninja import Router as APIRouter
from ninja import Schema
from pydantic import Field as APIField

from c3nav.api.newauth import auth_responses
from c3nav.mapdata.models import Source
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.schemas.filters import BySearchableFilter, RemoveGeometryFilter
from c3nav.mapdata.schemas.models import FullLocationSchema, SlimLocationSchema
from c3nav.mapdata.schemas.responses import BoundsSchema
from c3nav.mapdata.utils.locations import searchable_locations_for_request, visible_locations_for_request

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


@map_api_router.get('/locations/', response={200: list[SlimLocationSchema], **auth_responses},
                    summary="Get locations (with most important attributes)")
def location_list(request, filters: Query[LocationListFilters]):
    return _location_list(request, detailed=False, filters=filters)


@map_api_router.get('/locations/full/', response={200: list[FullLocationSchema], **auth_responses},
                    summary="Get locations (with all attributes)")
def location_list_full(request, filters: Query[LocationListFilters]):
    return _location_list(request, detailed=True, filters=filters)
