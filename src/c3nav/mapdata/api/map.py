import json
import math
import operator
from collections import defaultdict
from functools import reduce
from itertools import chain
from typing import Annotated, Union, Optional, Sequence

from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q
from django.db.models.query import Prefetch
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from ninja import Query
from ninja import Router as APIRouter
from pydantic import Field as APIField
from pydantic import PositiveInt

from c3nav import settings
from c3nav.api.auth import auth_permission_responses, auth_responses, validate_responses
from c3nav.api.exceptions import API404, APIPermissionDenied, APIRequestValidationFailed
from c3nav.api.schema import BaseSchema, GeometriesByLevelSchema
from c3nav.mapdata.api.base import api_etag, api_stats
from c3nav.mapdata.grid import grid
from c3nav.mapdata.locations import LocationRedirect, LocationManager
from c3nav.mapdata.models import Theme, Area, Space, Level
from c3nav.mapdata.models.geometry.space import ObstacleGroup, Obstacle, RangingBeacon
from c3nav.mapdata.models.locations import Position, LoadGroup, LocationTag
from c3nav.mapdata.quests.base import QuestSchema, get_all_quests_for_request
from c3nav.mapdata.render.theme import ColorManager
from c3nav.mapdata.schemas.locations import LocationDisplay, SingleLocationItemSchema, ListedLocationItemSchema
from c3nav.mapdata.schemas.model_base import LocationIdentifier, CustomLocationIdentifier, PositionIdentifier
from c3nav.mapdata.schemas.models import ProjectionPipelineSchema, ProjectionSchema, LegendSchema, LegendItemSchema
from c3nav.mapdata.schemas.responses import WithBoundsSchema, MapSettingsSchema
from c3nav.mapdata.utils.geometry.wrapped import unwrap_geom
from c3nav.mapdata.utils.user import can_access_editor

map_api_router = APIRouter(tags=["map"])


@map_api_router.get('/settings/', summary="get map settings",
                    description="get useful/required settings for displaying the map",
                    response={200: MapSettingsSchema, **auth_responses})
@api_etag(permissions=False)
def map_settings(request):
    initial_bounds = settings.INITIAL_BOUNDS
    if not initial_bounds:
        initial_bounds = tuple(chain(*Level.max_bounds()))
    else:
        initial_bounds = (tuple(settings.INITIAL_BOUNDS)[:2], tuple(settings.INITIAL_BOUNDS)[2:])

    return MapSettingsSchema(
        initial_bounds=initial_bounds,
        initial_level=settings.INITIAL_LEVEL or None,
        grid=grid if grid else None,
        tile_server=settings.TILE_CACHE_SERVER,
    )


@map_api_router.get('/bounds/', summary="get boundaries",
                    description="get maximum boundaries of everything on the map",
                    response={200: WithBoundsSchema, **auth_responses})
@api_etag(cache_job_types=("mapdata.recalculate_geometries", ), permissions=False)
def bounds(request):
    return {
        "bounds": Level.max_bounds(),
    }


class LocationEndpointParameters(BaseSchema):
    searchable: bool = APIField(
        False,
        title='only list searchable locations',
        description='if set, only searchable locations will be listed'
    )


class LocationListFilters(BaseSchema):
    searchable: bool = APIField(
        False,
        title='searchable locations only',
        description='only show locations that should show up in search'
    )


@map_api_router.get('/locations/', summary="list locations",
                    description="Get locations",
                    response={200: list[ListedLocationItemSchema], **validate_responses, **auth_responses})
@api_etag(cache_job_types=("mapdata.recalculate_locationtag_final", ))
def location_list(request, filters: Query[LocationListFilters]):
    if filters.searchable:
        return LocationManager.get_searchable_sorted()
    return LocationManager.get_visible_sorted()


class ShowRedirects(BaseSchema):
    show_redirects: bool = APIField(
        False,
        title="show redirects",
        description="whether to show redirects instead of sending a redirect response",
    )


@map_api_router.get('/locations/{identifier}/', summary="get location",
                    description="Retrieve location",
                    response={200: SingleLocationItemSchema, **API404.dict(), **validate_responses, **auth_responses})
@api_stats('location_get')
@api_etag(cache_job_types=("mapdata.recalculate_locationtag_final", ))  # todo: custom location changes later
def get_location(request, identifier: LocationIdentifier, redirects: Query[ShowRedirects]):
    location = LocationManager.get(identifier)

    if location is None:
        raise API404()

    if isinstance(location, LocationRedirect):
        if not redirects.show_redirects:
            return redirect(reverse("api-v2:get_location", kwargs={
                "identifier": location.target.effective_slug,
            }))

    if location.dynamic:
        request._target_etag = None
        request._target_cache_key = None

    return location


@map_api_router.get('/locations/{identifier}/display/', summary="location display",
                    description="Retrieve displayable information about a location",
                    response={200: LocationDisplay, **API404.dict(), **auth_responses})
@api_stats('location_display')  # todo: api stats should go by ID maybe?
@api_etag(cache_job_types=("mapdata.recalculate_locationtag_final", ))  # todo: custom location changes later
def location_display(request, identifier: LocationIdentifier):
    location = LocationManager.get(identifier)
    if location is None:
        raise API404()

    if isinstance(location, LocationRedirect):
        return redirect(reverse("api-v2:location_display", kwargs={
            "identifier": location.target.effective_slug,
        }))

    location = location.details_display(
        editor_url=can_access_editor(request),
    )
    return json.loads(json.dumps(location, cls=DjangoJSONEncoder))  # todo: needed to get rid of lazy strings=


@map_api_router.get('/locations/{identifier}/geometries/', summary="location geometries",
                    description="Get location geometries (if available)",
                    response={200: GeometriesByLevelSchema, **API404.dict(), **auth_responses})
@api_stats('location_geometries')
@api_etag(base_mapdata=True, cache_job_types=("mapdata.recalculate_locationtag_final", ))
def location_geometries(request, identifier: LocationIdentifier):
    location = LocationManager.get(identifier)

    if location is None:
        raise API404()

    if isinstance(location, LocationRedirect):
        return redirect(reverse("api-v2:location_geometries", kwargs={
            "identifier": location.target.effective_slug,
        }))

    return location.geometries_by_level


@map_api_router.get('/positions/my/', summary="all moving position coordinates",
                    description="get current coordinates of all moving positions owned be the current users",
                    response={200: list[SingleLocationItemSchema], **API404.dict(), **auth_responses})
@api_stats('get_positions')
def get_my_positions(request) -> Sequence[Position]:
    # no caching for obvious reasons!
    return Position.objects.filter(owner=request.user)


class UpdatePositionSchema(BaseSchema):
    coordinates_id: Union[
        Annotated[CustomLocationIdentifier, APIField(title="set coordinates")],
        Annotated[None, APIField(title="unset coordinates")],
    ] = APIField(
        description="coordinates to set the location to or null to unset it"
    )
    timeout: Union[
        Annotated[PositiveInt, APIField(title="new timeout")],
        Annotated[None, APIField(title="don't change")],
    ] = APIField(
        None,
        title="timeout",
        description="timeout for this new location in seconds, or None if not to change it",
    )


@map_api_router.put('/positions/{position_id}/', url_name="position-update",
                    summary="set moving position",
                    description="only the string ID for the position secret must be used",
                    response={200: SingleLocationItemSchema, **API404.dict(), **auth_permission_responses})
def set_position(request, position_id: PositionIdentifier, update: UpdatePositionSchema):
    # todo: may an API key do this?
    try:
        location = Position.objects.get(secret=position_id[2:])
    except Position.DoesNotExist:
        raise API404()
    if location.owner != request.user:
        raise APIPermissionDenied()

    coordinates = LocationManager.get(update.coordinates_id)
    if coordinates is None:
        raise APIRequestValidationFailed('Cant resolve coordinates.')

    location.coordinates_id = update.coordinates_id
    location.timeout = update.timeout or 0
    location.last_coordinates_update = timezone.now()
    location.save()

    return location


@map_api_router.get('/projection/', summary='get proj4 string',
                    description="get proj4 string for converting WGS84 coordinates to c3nva coordinates",
                    response={200: Union[ProjectionSchema, ProjectionPipelineSchema], **auth_responses})
def get_projection(request):
    obj = {
        "pipeline": settings.PROJECTION_TRANSFORMER_STRING
    }
    if True:
        obj.update({
            'proj4': settings.PROJECTION_PROJ4,
            'zero_point': settings.PROJECTION_ZERO_POINT,
            'rotation': settings.PROJECTION_ROTATION,
            'rotation_matrix': settings.PROJECTION_ROTATION_MATRIX,
        })
    return obj


"""
Legend
"""


@map_api_router.get('/legend/{theme_id}/', summary="get legend",
                        description="Get legend / color key for theme",
                        response={200: LegendSchema, **API404.dict(), **auth_responses})
@api_etag(cache_job_types=("mapdata.recalculate_locationtag_final", ), permissions=True)
def legend_for_theme(request, theme_id: int):
    try:
        manager = ColorManager.for_theme(theme_id or None)
    except Theme.DoesNotExist:
        raise API404()
    legend_tags = sorted([
        tag for tag in LocationTag.objects.filter(in_legend=True)
        if tag.descendants or tag.cached_all_static_targets
    ], key=lambda tag: tag.get_color_order(manager))
    obstaclegroups = ObstacleGroup.objects.filter(
        in_legend=True,
        pk__in=set(Obstacle.objects.filter(group__isnull=False).values_list('group', flat=True)),
    )
    return LegendSchema(
        base=[],
        groups=[item for item in (LegendItemSchema(title=tag.title,
                                                   fill=manager.location_tag_fill_color(tag),
                                                   border=manager.location_border_color(tag))
                                  for tag in legend_tags)
                if item.fill or item.border],
        obstacles=[item for item in (LegendItemSchema(title=group.title,
                                                      fill=manager.obstaclegroup_fill_color(group),
                                                      border=manager.obstaclegroup_border_color(group))
                                     for group in obstaclegroups)
                   if item.fill or item.border],
    )


""" 
Quests 
"""


class QuestsFilter(BaseSchema):
    quest_type: Optional[str] = APIField(
        None,
        title="only show these quest types",
        description="multiple quest types can be comma-separated"
    )
    level: Optional[PositiveInt] = APIField(
        None,
        title="only show quests for this level",
    )


@map_api_router.get('/quests/', summary="get open quests",
                    response={200: list[QuestSchema], **auth_responses})
@api_etag(permissions=True, quests=True)
def list_quests(request, filters: Query[QuestsFilter]):
    quest_types = filters.quest_type.split(',') if filters.quest_type else None
    quests = get_all_quests_for_request(request, quest_types)

    if filters.level:
        quests = [quest for quest in quests if quest.level_id == filters.level]
    return quests


"""
Room load
"""


@map_api_router.get('/load/', summary="get load group loads",
                    response={200: dict[PositiveInt, float], **auth_responses})
def get_load(request):
    result = cache.get('mapdata:get_load', None)
    if result is not None:
        return result

    if not cache.get('mapdata:load_is_recent', False):
        return {}

    load_groups = {g.pk: g for g in LoadGroup.objects.all()}

    # per group
    max_values: dict[int, int] = {pk: 0 for pk in load_groups.keys()}
    current_values: dict[int, int] = {pk: 0 for pk in load_groups.keys()}

    beacons_by_space = {}
    for beacon in RangingBeacon.objects.filter(max_observed_num_clients__gt=0):
        beacons_by_space.setdefault(beacon.space_id, {})[beacon.pk] = beacon

    # todo: better caching?

    tags_contribute_to: dict[int, set[int]] = defaultdict(set)
    for tag in LocationTag.objects.filter(load_group_contribute__isnull=False):
        for tag_id in chain((tag.pk,), tag.descendants):
            tags_contribute_to[tag_id].add(tag.load_group_contribute_to)

    for area in Area.objects.filter(tags__in=tags_contribute_to.keys()).prefetch_related(
        Prefetch("tags", LocationTag.objects.without_inherited().only("pk"))
    ):
        contribute_to = reduce(operator.or_, (tags_contribute_to[tag.pk] for tag in area.tags.all()), set())
        for beacon in beacons_by_space.get(area.space_id, {}).values():
            if area.geometry.intersects(unwrap_geom(beacon.geometry)):
                for load_group_id in contribute_to:
                    max_values[load_group_id] += beacon.max_observed_num_clients
                    current_values[load_group_id] += beacon.num_clients

    for space in Space.objects.filter(tags__in=tags_contribute_to.keys()).prefetch_related(
        Prefetch("tags", LocationTag.objects.without_inherited().only("pk"))
    ):
        contribute_to = reduce(operator.or_, (tags_contribute_to[tag.pk] for tag in space.tags.all()), set())
        for beacon in beacons_by_space.get(space.pk, {}).values():
            for load_group_id in contribute_to:
                max_values[load_group_id] += beacon.max_observed_num_clients
                current_values[load_group_id] += beacon.num_clients

    result = {
        pk: math.sin(3.14159 / 2 * (max(current_values[pk] / max_value - 0.2, 0) / 0.65)) if max_value else 0
        for pk, max_value in max_values.items()
    }
    cache.set('mapdata:get_load', result, 300)
    return result


class ApLoadSchema(BaseSchema):
    aps: dict[str, int]


@map_api_router.post('/load/', summary="update current load data",
                     response={204: None, **auth_permission_responses})
def post_load(request, parameters: ApLoadSchema):
    if not request.user_permissions.can_write_load_data:
        raise APIPermissionDenied()

    names = parameters.aps.keys()

    with transaction.atomic():
        for beacon in RangingBeacon.objects.filter(ap_name__in=names):
            beacon.num_clients = parameters.aps[beacon.ap_name]
            if beacon.num_clients > beacon.max_observed_num_clients:
                beacon.max_observed_num_clients = beacon.num_clients
            beacon.save()

    cache.delete('mapdata:get_load')
    cache.set('mapdata:load_is_recent', True, 300)

    return 204, None
