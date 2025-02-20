import json
import math
from typing import Annotated, Union, Optional, Sequence

from celery import chain
from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Prefetch, Q
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
from c3nav.api.schema import BaseSchema
from c3nav.mapdata.api.base import api_etag, api_stats
from c3nav.mapdata.grid import grid
from c3nav.mapdata.models import Source, Theme, Area, Space
from c3nav.mapdata.models.geometry.space import AutoBeaconMeasurement, \
    BeaconMeasurement
from c3nav.mapdata.models.geometry.space import ObstacleGroup, Obstacle, RangingBeacon
from c3nav.mapdata.models.locations import DynamicLocation, Position, LocationGroup, LoadGroup, SpecificLocation
from c3nav.mapdata.quests.base import QuestSchema, get_all_quests_for_request
from c3nav.mapdata.render.theme import ColorManager
from c3nav.mapdata.schemas.filters import BySearchableFilter
from c3nav.mapdata.schemas.locations import LocationDisplay, SingleLocationItemSchema, ListedLocationItemSchema
from c3nav.mapdata.schemas.model_base import LocationIdentifier, CustomLocationIdentifier, PositionIdentifier
from c3nav.mapdata.schemas.models import ProjectionPipelineSchema, ProjectionSchema, LegendSchema, LegendItemSchema
from c3nav.mapdata.schemas.responses import LocationGeometry, WithBoundsSchema, MapSettingsSchema
from c3nav.mapdata.utils.geometry import unwrap_geom
from c3nav.mapdata.utils.locations import (searchable_locations_for_request,
                                           visible_locations_for_request,
                                           LocationRedirect, get_location_for_request)
from c3nav.mapdata.utils.user import can_access_editor

map_api_router = APIRouter(tags=["map"])


@map_api_router.get('/settings/', summary="get map settings",
                    description="get useful/required settings for displaying the map",
                    response={200: MapSettingsSchema, **auth_responses})
@api_etag(permissions=False)
def map_settings(request):
    initial_bounds = settings.INITIAL_BOUNDS
    if not initial_bounds:
        initial_bounds = tuple(chain(*Source.max_bounds()))
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
@api_etag(permissions=False)
def bounds(request):
    return {
        "bounds": Source.max_bounds(),
    }


class LocationEndpointParameters(BaseSchema):
    searchable: bool = APIField(
        False,
        title='only list searchable locations',
        description='if set, only searchable locations will be listed'
    )


class LocationListFilters(BySearchableFilter):
    pass


@map_api_router.get('/locations/', summary="list locations",
                    description="Get locations",
                    response={200: list[ListedLocationItemSchema], **validate_responses, **auth_responses})
@api_etag(base_mapdata=True)
def location_list(request, filters: Query[LocationListFilters]):
    if filters.searchable:
        return searchable_locations_for_request(request).values()
    return visible_locations_for_request(request).values()


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
@api_etag(base_mapdata=True)
def get_location(request, identifier: LocationIdentifier, redirects: Query[ShowRedirects]):
    location = get_location_for_request(identifier, request)

    if location is None:
        raise API404()

    if isinstance(location, LocationRedirect):
        if not redirects.show_redirects:
            return redirect(reverse("api-v2:get-location", kwargs={
                "identifier": location.target.effective_slug,
            }))

    if isinstance(location, (DynamicLocation, Position)):
        # todo: what does this do?
        request._target_etag = None
        request._target_cache_key = None

    return location


@map_api_router.get('/locations/{identifier}/display/', summary="location display",
                    description="Retrieve displayable information about location",
                    response={200: LocationDisplay, **API404.dict(), **auth_responses})
@api_stats('location_display')  # todo: api stats should go by ID maybe?
@api_etag(base_mapdata=True)
def location_display(request, identifier: LocationIdentifier):
    location = get_location_for_request(identifier, request)
    if location is None:
        raise API404()

    if isinstance(location, LocationRedirect):
        return redirect(reverse("api-v2:location-display", kwargs={
            "identifier": location.target.effective_slug,
        }))

    location = location.details_display(
        request=request,
        editor_url=can_access_editor(request),
    )
    return json.loads(json.dumps(location, cls=DjangoJSONEncoder))  # todo: wtf?? well we need to get rid of lazy strings


@map_api_router.get('/locations/{identifier}/geometry/', summary="location geometry",
                    description="Get location geometry (if available)",
                    response={200: LocationGeometry, **API404.dict(), **auth_responses})
@api_stats('location_geometry')
@api_etag(base_mapdata=True)
def location_geometry(request, identifier: LocationIdentifier):
    location = get_location_for_request(identifier, request)

    if location is None:
        raise API404()

    if isinstance(location, LocationRedirect):
        return redirect(reverse("api-v2:location-geometry", kwargs={
            "identifier": location.target.effective_slug,
        }))

    return LocationGeometry(
        identifier=identifier,
        geometry=location.get_geometry(request)
    )


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

    coordinates = get_location_for_request(update.coordinates_id, request)
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
                        description="Get legend / color key fo theme",
                        response={200: LegendSchema, **API404.dict(), **auth_responses})
@api_etag(permissions=True)
def legend_for_theme(request, theme_id: int):
    try:
        manager = ColorManager.for_theme(theme_id or None)
    except Theme.DoesNotExist:
        raise API404()
    locationgroups = LocationGroup.qs_for_request(request).filter(in_legend=True).prefetch_related(
        Prefetch('specific_locations', SpecificLocation.qs_for_request(request))
    )
    obstaclegroups = ObstacleGroup.objects.filter(
        in_legend=True,
        pk__in=set(Obstacle.qs_for_request(request).filter(group__isnull=False).values_list('group', flat=True)),
    )
    return LegendSchema(
        base=[],
        groups=[item for item in (LegendItemSchema(title=group.title,
                                                   fill=manager.locationgroup_fill_color(group),
                                                   border=manager.locationgroup_border_color(group))
                                  for group in locationgroups if group.specific_locations.all())
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

    locationgroups_contribute_to = dict(
        LocationGroup.objects.filter(load_group_contribute__isnull=False).values_list("pk", "load_group_contribute")
    )
    for area in Area.objects.filter((Q(load_group_contribute__isnull=False)
                                     | Q(groups__in=locationgroups_contribute_to.keys()))).prefetch_related("groups"):
        contribute_to = set()
        if area.load_group_contribute_id:
            contribute_to.add(area.load_group_contribute_id)
        for group in area.groups.all():
            if group.load_group_contribute_id:
                contribute_to.add(group.load_group_contribute_id)
        for beacon in beacons_by_space.get(area.space_id, {}).values():
            if area.geometry.intersects(unwrap_geom(beacon.geometry)):
                for load_group_id in contribute_to:
                    max_values[load_group_id] += beacon.max_observed_num_clients
                    current_values[load_group_id] += beacon.num_clients

    for space in Space.objects.filter((Q(load_group_contribute__isnull=False)
                                      | Q(groups__in=locationgroups_contribute_to.keys()))).prefetch_related("groups"):
        contribute_to = set()
        if space.load_group_contribute_id:
            contribute_to.add(space.load_group_contribute_id)
        for group in space.groups.all():
            if group.load_group_contribute_id:
                contribute_to.add(group.load_group_contribute_id)
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


@map_api_router.get('/wifidata/', summary="wifidata special",
                    response={200: dict, **auth_responses})
def wifidata(request):
    # todo: this is ugly because i'm tired, wehhhh
    if not request.user.has_perm("mapdata.view_autobeaconmeasurement"):
        raise APIPermissionDenied()

    result = {
        "rangingbeacons": [],
        "autobeaconmeasurements": [],
        "beaconmeasurements": [],
    }
    for m in AutoBeaconMeasurement.objects.select_related("author"):
        result["autobeaconmeasurements"].append({
            "pk": m.pk,
            "author": m.author.username,
            "datetime": str(m.datetime),
            "data": m.data.model_dump(),
        })

    from c3nav.routing.router import Router
    router = Router.load()
    for m in BeaconMeasurement.objects.select_related("author"):
        result["beaconmeasurements"].append({
            "pk": m.pk,
            "author": m.author.username,
            "comment": m.comment,
            "space_id": m.space_id,
            "xyz_floor": (
                int(m.geometry.x*100), int(m.geometry.y*100),
                int(router.spaces[m.space_id].altitudearea_for_point(m.geometry).get_altitude(m.geometry)*100),
            ),
            "data": m.data.model_dump(),
        })

    from c3nav.routing.locator import Locator
    l = Locator.load()
    for peer in l.peers:
        if not peer.identifier.identifier.startswith('AP'):
            continue
        result["rangingbeacons"].append({
            "name": peer.identifier.identifier,
            "xyz": peer.xyz,
            "space_id": peer.space_id,
        })

    return result