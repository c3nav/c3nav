from typing import Optional, Sequence, Type

from django.db.models import Model
from ninja import Query
from ninja import Router as APIRouter
from ninja.pagination import paginate

from c3nav.api.exceptions import API404
from c3nav.mapdata.api import optimize_query
from c3nav.mapdata.models import (Area, Building, Door, Hole, Level, LocationGroup, LocationGroupCategory, Source,
                                  Space, Stair)
from c3nav.mapdata.models.access import AccessPermission, AccessRestriction, AccessRestrictionGroup
from c3nav.mapdata.models.geometry.space import (POI, Column, CrossDescription, LeaveDescription, LineObstacle,
                                                 Obstacle, Ramp)
from c3nav.mapdata.schemas.filters import (ByCategoryFilter, ByGroupFilter, ByLevelFilter, ByOnTopOfFilter,
                                           BySpaceFilter, FilterSchema)
from c3nav.mapdata.schemas.models import (AccessRestrictionGroupSchema, AccessRestrictionSchema, AreaSchema,
                                          BuildingSchema, ColumnSchema, CrossDescriptionSchema, DoorSchema, HoleSchema,
                                          LeaveDescriptionSchema, LevelSchema, LineObstacleSchema,
                                          LocationGroupCategorySchema, LocationGroupSchema, ObstacleSchema, POISchema,
                                          RampSchema, SourceSchema, SpaceSchema, StairSchema)

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


"""
LeaveDescriptions
"""


@mapdata_api_router.get('/leavedescriptions/', response=list[LeaveDescriptionSchema],
                        summary="Get leave description list")
@paginate
def leavedescription_list(request, filters: Query[BySpaceFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=LeaveDescription, filters=filters)


@mapdata_api_router.get('/leavedescriptions/{leavedescription_id}/', response=LeaveDescriptionSchema,
                        summary="Get leave description by ID")
def leavedescription_detail(request, leavedescription_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, LeaveDescription, pk=leavedescription_id)


"""
CrossDescriptions
"""


@mapdata_api_router.get('/crossdescriptions/', response=list[CrossDescriptionSchema],
                        summary="Get cross description list")
@paginate
def crossdescription_list(request, filters: Query[BySpaceFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=CrossDescription, filters=filters)


@mapdata_api_router.get('/crossdescriptions/{crossdescription_id}/', response=CrossDescriptionSchema,
                        summary="Get cross description by ID")
def crossdescription_detail(request, crossdescription_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, CrossDescription, pk=crossdescription_id)


"""
LocationGroup
"""


@mapdata_api_router.get('/locationgroups/', response=list[LocationGroupSchema],
                        summary="Get location group list")
@paginate
def locationgroup_list(request, filters: Query[ByCategoryFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=LocationGroup, filters=filters)


@mapdata_api_router.get('/locationgroups/{locationgroup_id}/', response=LocationGroupSchema,
                        summary="Get location group by ID")
def locationgroup_detail(request, locationgroup_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, LocationGroup, pk=locationgroup_id)


"""
LocationGroupCategories
"""


@mapdata_api_router.get('/locationgroupcategories/', response=list[LocationGroupCategorySchema],
                        summary="Get location group category list")
@paginate
def locationgroupcategory_list(request):
    # todo cache?
    return mapdata_list_endpoint(request, model=LocationGroupCategory)


@mapdata_api_router.get('/locationgroupcategories/{category_id}/', response=LocationGroupCategorySchema,
                        summary="Get location group category by ID")
def locationgroupcategory_detail(request, category_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, LocationGroupCategory, pk=category_id)


"""
Sources
"""


@mapdata_api_router.get('/sources/', response=list[SourceSchema],
                        summary="Get source list")
@paginate
def source_list(request):
    # todo cache?
    return mapdata_list_endpoint(request, model=Source)


@mapdata_api_router.get('/sources/{source_id}/', response=SourceSchema,
                        summary="Get source by ID")
def source_detail(request, source_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Source, pk=source_id)


"""
AccessRestrictions
"""


@mapdata_api_router.get('/accessrestrictions/', response=list[AccessRestrictionSchema],
                        summary="Get access restriction list")
@paginate
def accessrestriction_list(request):
    # todo cache?
    return mapdata_list_endpoint(request, model=AccessRestriction)


@mapdata_api_router.get('/accessrestrictions/{accessrestriction_id}/', response=AccessRestrictionSchema,
                        summary="Get access restriction by ID")
def accessrestriction_detail(request, accessrestriction_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, AccessRestriction, pk=accessrestriction_id)


"""
AccessRestrictionGroups
"""


@mapdata_api_router.get('/accessrestrictiongroups/', response=list[AccessRestrictionGroupSchema],
                        summary="Get access restriction group list")
@paginate
def accessrestrictiongroup_list(request):
    # todo cache?
    return mapdata_list_endpoint(request, model=AccessRestrictionGroup)


@mapdata_api_router.get('/accessrestrictiongroups/{group_id}/', response=AccessRestrictionGroupSchema,
                        summary="Get access restriction group by ID")
def accessrestrictiongroups_detail(request, group_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, AccessRestrictionGroup, pk=group_id)
