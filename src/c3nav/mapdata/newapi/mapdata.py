from typing import Optional, Sequence, Type

from django.db.models import Model
from ninja import Query
from ninja import Router as APIRouter
from ninja.pagination import paginate

from c3nav.api.exceptions import API404
from c3nav.mapdata.api import optimize_query
from c3nav.mapdata.models import Area, Building, Door, Hole, Level, Space, Stair
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.models.geometry.space import POI, Column, LineObstacle, Obstacle, Ramp
from c3nav.mapdata.schemas.filters import ByGroupFilter, ByLevelFilter, ByOnTopOfFilter, BySpaceFilter, FilterSchema
from c3nav.mapdata.schemas.models import (AreaSchema, BuildingSchema, ColumnSchema, DoorSchema, HoleSchema, LevelSchema,
                                          LineObstacleSchema, ObstacleSchema, POISchema, RampSchema, SpaceSchema,
                                          StairSchema)

mapdata_api_router = APIRouter(tags=["mapdata"])


def mapdata_list_endpoint(request,
                          model: Type[Model],
                          filters: Optional[FilterSchema] = None,
                          order_by: Sequence[str] = ('pk',)):
    # todo: request permissions based on api key

    # todo: pagination cache?

    # generate cache_key
    # todo: don't ignore request language
    cache_key = 'mapdata:api:%s:%s' % (model.__name__, AccessPermission.cache_key_for_request(request))
    if filters:
        for name in filters.model_fields_set:  # noqa
            value = getattr(filters, name)
            if value is None:
                continue
            cache_key += ';%s,%s' % (name, value)

    # todo: we have the cache key, this would be a great time for a shortcut

    # validate filters
    if filters:
        filters.validate(request)

    # get the queryset and filter it
    qs = optimize_query(
        model.qs_for_request(request) if hasattr(model, 'qs_for_request') else model.objects.all()
    )
    if filters:
        qs = filters.filter_qs(qs)

    # order_by
    qs = qs.order_by(*order_by)

    # todo: can access geometry… using defer?

    return qs


def mapdata_retrieve_endpoint(request, model: Type[Model], **lookups):
    try:
        return optimize_query(
            model.qs_for_request(request) if hasattr(model, 'qs_for_request') else model.objects.all()
        ).get(**lookups)
    except model.DoesNotExist:
        raise API404("%s not found" % model.__name__.lower())


"""
Levels
"""


class LevelFilters(ByGroupFilter, ByOnTopOfFilter):
    pass


@mapdata_api_router.get('/levels/', response=list[LevelSchema],
                        summary="Get level list")
@paginate
def level_list(request, filters: Query[LevelFilters]):
    # todo cache?
    return mapdata_list_endpoint(request, model=Level, filters=filters)


@mapdata_api_router.get('/levels/{level_id}/', response=LevelSchema,
                        summary="Get level by ID")
def level_detail(request, level_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Level, pk=level_id)


"""
Buildings
"""


@mapdata_api_router.get('/buildings/', response=list[BuildingSchema],
                        summary="Get building list")
@paginate
def building_list(request, filters: Query[ByLevelFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=Building, filters=filters)


@mapdata_api_router.get('/buildings/{building_id}/', response=BuildingSchema,
                        summary="Get building by ID")
def building_detail(request, building_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Building, pk=building_id)


"""
Spaces
"""


class SpaceFilters(ByGroupFilter, ByLevelFilter):
    pass


@mapdata_api_router.get('/spaces/', response=list[SpaceSchema],
                        summary="Get space list")
@paginate
def space_list(request, filters: Query[SpaceFilters]):
    # todo cache?
    return mapdata_list_endpoint(request, model=Space, filters=filters)


@mapdata_api_router.get('/space/{space_id}/', response=SpaceSchema,
                        summary="Get space by ID")
def space_detail(request, space_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Space, pk=space_id)


"""
Doors
"""


@mapdata_api_router.get('/doors/', response=list[DoorSchema],
                        summary="Get door list")
@paginate
def door_list(request, filters: Query[ByLevelFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=Door, filters=filters)


@mapdata_api_router.get('/doors/{door_id}/', response=DoorSchema,
                        summary="Get door by ID")
def door_detail(request, door_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Door, pk=door_id)


"""
Holes
"""


@mapdata_api_router.get('/holes/', response=list[HoleSchema],
                        summary="Get hole list")
@paginate
def hole_list(request, filters: Query[BySpaceFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=Hole, filters=filters)


@mapdata_api_router.get('/holes/{hole_id}/', response=HoleSchema,
                        summary="Get hole by ID")
def hole_detail(request, hole_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Hole, pk=hole_id)


"""
Areas
"""


class AreaFilters(ByGroupFilter, BySpaceFilter):
    pass


@mapdata_api_router.get('/areas/', response=list[AreaSchema],
                        summary="Get area list")
@paginate
def area_list(request, filters: Query[AreaFilters]):
    # todo cache?
    return mapdata_list_endpoint(request, model=Area, filters=filters)


@mapdata_api_router.get('/areas/{area_id}/', response=AreaSchema,
                        summary="Get area by ID")
def area_detail(request, area_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Area, pk=area_id)


"""
Stairs
"""


@mapdata_api_router.get('/stairs/', response=list[StairSchema],
                        summary="Get stair list")
@paginate
def stair_list(request, filters: Query[BySpaceFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=Stair, filters=filters)


@mapdata_api_router.get('/stairs/{stair_id}/', response=StairSchema,
                        summary="Get stair by ID")
def stair_detail(request, stair_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Stair, pk=stair_id)


"""
Ramps
"""


@mapdata_api_router.get('/ramps/', response=list[RampSchema],
                        summary="Get ramp list")
@paginate
def ramp_list(request, filters: Query[BySpaceFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=Ramp, filters=filters)


@mapdata_api_router.get('/ramps/{ramp_id}/', response=RampSchema,
                        summary="Get ramp by ID")
def ramp_detail(request, ramp_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Ramp, pk=ramp_id)


"""
Obstacles
"""


@mapdata_api_router.get('/obstacles/', response=list[ObstacleSchema],
                        summary="Get obstacle list")
@paginate
def obstacle_list(request, filters: Query[BySpaceFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=Obstacle, filters=filters)


@mapdata_api_router.get('/obstacles/{obstacle_id}/', response=ObstacleSchema,
                        summary="Get obstacle by ID")
def obstacle_detail(request, obstacle_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Obstacle, pk=obstacle_id)


"""
LineObstacles
"""


@mapdata_api_router.get('/lineobstacles/', response=list[LineObstacleSchema],
                        summary="Get line obstacle list")
@paginate
def lineobstacle_list(request, filters: Query[BySpaceFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=LineObstacle, filters=filters)


@mapdata_api_router.get('/lineobstacles/{lineobstacle_id}/', response=LineObstacleSchema,
                        summary="Get line obstacle by ID")
def lineobstacle_detail(request, lineobstacle_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, LineObstacle, pk=lineobstacle_id)


"""
Columns
"""


@mapdata_api_router.get('/columns/', response=list[ColumnSchema],
                        summary="Get column list")
@paginate
def column_list(request, filters: Query[BySpaceFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=Column, filters=filters)


@mapdata_api_router.get('/columns/{column_id}/', response=ColumnSchema,
                        summary="Get column by ID")
def column_detail(request, column_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Column, pk=column_id)


"""
POIs
"""


@mapdata_api_router.get('/pois/', response=list[POISchema],
                        summary="Get POI list")
@paginate
def poi_list(request, filters: Query[BySpaceFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=POI, filters=filters)


@mapdata_api_router.get('/pois/{poi_id}/', response=POISchema,
                        summary="Get POI by ID")
def poi_detail(request, poi_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, POI, pk=poi_id)
