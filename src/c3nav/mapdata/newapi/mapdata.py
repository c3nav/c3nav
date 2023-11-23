from typing import Optional, Sequence, Type

from django.db.models import Model
from ninja import Query
from ninja import Router as APIRouter
from ninja.pagination import paginate

from c3nav.api.exceptions import API404
from c3nav.api.newauth import auth_responses, validate_responses
from c3nav.mapdata.api import optimize_query
from c3nav.mapdata.models import (Area, Building, Door, Hole, Level, LocationGroup, LocationGroupCategory, Source,
                                  Space, Stair)
from c3nav.mapdata.models.access import AccessPermission, AccessRestriction, AccessRestrictionGroup
from c3nav.mapdata.models.geometry.space import (POI, Column, CrossDescription, LeaveDescription, LineObstacle,
                                                 Obstacle, Ramp)
from c3nav.mapdata.models.locations import DynamicLocation
from c3nav.mapdata.schemas.filters import (ByCategoryFilter, ByGroupFilter, ByOnTopOfFilter, FilterSchema,
                                           LevelGeometryFilter, SpaceGeometryFilter)
from c3nav.mapdata.schemas.models import (AccessRestrictionGroupSchema, AccessRestrictionSchema, AreaSchema,
                                          BuildingSchema, ColumnSchema, CrossDescriptionSchema, DoorSchema,
                                          DynamicLocationSchema, HoleSchema, LeaveDescriptionSchema, LevelSchema,
                                          LineObstacleSchema, LocationGroupCategorySchema, LocationGroupSchema,
                                          ObstacleSchema, POISchema, RampSchema, SourceSchema, SpaceSchema, StairSchema)

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


@mapdata_api_router.get('/levels/',
                        response={200: list[LevelSchema], **validate_responses, **auth_responses},
                        summary="Get level list")
@paginate
def level_list(request, filters: Query[LevelFilters]):
    # todo cache?
    return mapdata_list_endpoint(request, model=Level, filters=filters)


@mapdata_api_router.get('/levels/{level_id}/',
                        response={200: LevelSchema, **API404.dict(), **auth_responses},
                        summary="Get level by ID")
def level_by_id(request, level_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Level, pk=level_id)


"""
Buildings
"""


@mapdata_api_router.get('/buildings/',
                        response={200: list[BuildingSchema], **validate_responses, **auth_responses},
                        summary="Get building list")
@paginate
def building_list(request, filters: Query[LevelGeometryFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=Building, filters=filters)


@mapdata_api_router.get('/buildings/{building_id}/',
                        response={200: BuildingSchema, **API404.dict(), **auth_responses},
                        summary="Get building by ID")
def building_by_id(request, building_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Building, pk=building_id)


"""
Spaces
"""


class SpaceFilters(ByGroupFilter, LevelGeometryFilter):
    pass


@mapdata_api_router.get('/spaces/',
                        response={200: list[SpaceSchema], **validate_responses, **auth_responses},
                        summary="Get space list")
@paginate
def space_list(request, filters: Query[SpaceFilters]):
    # todo cache?
    return mapdata_list_endpoint(request, model=Space, filters=filters)


@mapdata_api_router.get('/space/{space_id}/',
                        response={200: SpaceSchema, **API404.dict(), **auth_responses},
                        summary="Get space by ID")
def space_by_id(request, space_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Space, pk=space_id)


"""
Doors
"""


@mapdata_api_router.get('/doors/',
                        response={200: list[DoorSchema], **validate_responses, **auth_responses},
                        summary="Get door list")
@paginate
def door_list(request, filters: Query[LevelGeometryFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=Door, filters=filters)


@mapdata_api_router.get('/doors/{door_id}/',
                        response={200: DoorSchema, **API404.dict(), **auth_responses},
                        summary="Get door by ID")
def door_by_id(request, door_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Door, pk=door_id)


"""
Holes
"""


@mapdata_api_router.get('/holes/',
                        response={200: list[HoleSchema], **validate_responses, **auth_responses},
                        summary="Get hole list")
@paginate
def hole_list(request, filters: Query[SpaceGeometryFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=Hole, filters=filters)


@mapdata_api_router.get('/holes/{hole_id}/',
                        response={200: HoleSchema, **API404.dict(), **auth_responses},
                        summary="Get hole by ID")
def hole_by_id(request, hole_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Hole, pk=hole_id)


"""
Areas
"""


class AreaFilters(ByGroupFilter, SpaceGeometryFilter):
    pass


@mapdata_api_router.get('/areas/',
                        response={200: list[AreaSchema], **validate_responses, **auth_responses},
                        summary="Get area list")
@paginate
def area_list(request, filters: Query[AreaFilters]):
    # todo cache?
    return mapdata_list_endpoint(request, model=Area, filters=filters)


@mapdata_api_router.get('/areas/{area_id}/',
                        response={200: AreaSchema, **API404.dict(), **auth_responses},
                        summary="Get area by ID")
def area_by_id(request, area_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Area, pk=area_id)


"""
Stairs
"""


@mapdata_api_router.get('/stairs/',
                        response={200: list[StairSchema], **validate_responses, **auth_responses},
                        summary="Get stair list")
@paginate
def stair_list(request, filters: Query[SpaceGeometryFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=Stair, filters=filters)


@mapdata_api_router.get('/stairs/{stair_id}/',
                        response={200: StairSchema, **API404.dict(), **auth_responses},
                        summary="Get stair by ID")
def stair_by_id(request, stair_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Stair, pk=stair_id)


"""
Ramps
"""


@mapdata_api_router.get('/ramps/',
                        response={200: list[RampSchema], **validate_responses, **auth_responses},
                        summary="Get ramp list")
@paginate
def ramp_list(request, filters: Query[SpaceGeometryFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=Ramp, filters=filters)


@mapdata_api_router.get('/ramps/{ramp_id}/',
                        response={200: RampSchema, **API404.dict(), **auth_responses},
                        summary="Get ramp by ID")
def ramp_by_id(request, ramp_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Ramp, pk=ramp_id)


"""
Obstacles
"""


@mapdata_api_router.get('/obstacles/',
                        response={200: list[ObstacleSchema], **validate_responses, **auth_responses},
                        summary="Get obstacle list")
@paginate
def obstacle_list(request, filters: Query[SpaceGeometryFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=Obstacle, filters=filters)


@mapdata_api_router.get('/obstacles/{obstacle_id}/',
                        response={200: ObstacleSchema, **API404.dict(), **auth_responses},
                        summary="Get obstacle by ID")
def obstacle_by_id(request, obstacle_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Obstacle, pk=obstacle_id)


"""
LineObstacles
"""


@mapdata_api_router.get('/lineobstacles/',
                        response={200: list[LineObstacleSchema], **validate_responses, **auth_responses},
                        summary="Get line obstacle list")
@paginate
def lineobstacle_list(request, filters: Query[SpaceGeometryFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=LineObstacle, filters=filters)


@mapdata_api_router.get('/lineobstacles/{lineobstacle_id}/',
                        response={200: LineObstacleSchema, **API404.dict(), **auth_responses},
                        summary="Get line obstacle by ID")
def lineobstacle_by_id(request, lineobstacle_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, LineObstacle, pk=lineobstacle_id)


"""
Columns
"""


@mapdata_api_router.get('/columns/',
                        response={200: list[ColumnSchema], **validate_responses, **auth_responses},
                        summary="Get column list")
@paginate
def column_list(request, filters: Query[SpaceGeometryFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=Column, filters=filters)


@mapdata_api_router.get('/columns/{column_id}/',
                        response={200: ColumnSchema, **API404.dict(), **auth_responses},
                        summary="Get column by ID")
def column_by_id(request, column_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Column, pk=column_id)


"""
POIs
"""


@mapdata_api_router.get('/pois/',
                        response={200: list[POISchema], **validate_responses, **auth_responses},
                        summary="Get POI list")
@paginate
def poi_list(request, filters: Query[SpaceGeometryFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=POI, filters=filters)


@mapdata_api_router.get('/pois/{poi_id}/',
                        response={200: POISchema, **API404.dict(), **auth_responses},
                        summary="Get POI by ID")
def poi_by_id(request, poi_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, POI, pk=poi_id)


"""
LeaveDescriptions
"""


@mapdata_api_router.get('/leavedescriptions/',
                        response={200: list[LeaveDescriptionSchema], **validate_responses, **auth_responses},
                        summary="Get leave description list")
@paginate
def leavedescription_list(request, filters: Query[SpaceGeometryFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=LeaveDescription, filters=filters)


@mapdata_api_router.get('/leavedescriptions/{leavedescription_id}/',
                        response={200: LeaveDescriptionSchema, **API404.dict(), **auth_responses},
                        summary="Get leave description by ID")
def leavedescription_by_id(request, leavedescription_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, LeaveDescription, pk=leavedescription_id)


"""
CrossDescriptions
"""


@mapdata_api_router.get('/crossdescriptions/',
                        response={200: list[CrossDescriptionSchema], **validate_responses, **auth_responses},
                        summary="Get cross description list")
@paginate
def crossdescription_list(request, filters: Query[SpaceGeometryFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=CrossDescription, filters=filters)


@mapdata_api_router.get('/crossdescriptions/{crossdescription_id}/',
                        response={200: CrossDescriptionSchema, **API404.dict(), **auth_responses},
                        summary="Get cross description by ID")
def crossdescription_by_id(request, crossdescription_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, CrossDescription, pk=crossdescription_id)


"""
LocationGroup
"""


@mapdata_api_router.get('/locationgroups/',
                        response={200: list[LocationGroupSchema], **validate_responses, **auth_responses},
                        summary="Get location group list")
@paginate
def locationgroup_list(request, filters: Query[ByCategoryFilter]):
    # todo cache?
    return mapdata_list_endpoint(request, model=LocationGroup, filters=filters)


@mapdata_api_router.get('/locationgroups/{locationgroup_id}/',
                        response={200: LocationGroupSchema, **API404.dict(), **auth_responses},
                        summary="Get location group by ID")
def locationgroup_by_id(request, locationgroup_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, LocationGroup, pk=locationgroup_id)


"""
LocationGroupCategories
"""


@mapdata_api_router.get('/locationgroupcategories/',
                        response={200: list[LocationGroupCategorySchema], **auth_responses},
                        summary="Get location group category list")
@paginate
def locationgroupcategory_list(request):
    # todo cache?
    return mapdata_list_endpoint(request, model=LocationGroupCategory)


@mapdata_api_router.get('/locationgroupcategories/{category_id}/',
                        response={200: LocationGroupCategorySchema, **API404.dict(), **auth_responses},
                        summary="Get location group category by ID")
def locationgroupcategory_by_id(request, category_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, LocationGroupCategory, pk=category_id)


"""
Sources
"""


@mapdata_api_router.get('/sources/',
                        response={200: list[SourceSchema], **auth_responses},
                        summary="Get source list")
@paginate
def source_list(request):
    # todo cache?
    return mapdata_list_endpoint(request, model=Source)


@mapdata_api_router.get('/sources/{source_id}/',
                        response={200: SourceSchema, **API404.dict(), **auth_responses},
                        summary="Get source by ID")
def source_by_id(request, source_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Source, pk=source_id)


"""
AccessRestrictions
"""


@mapdata_api_router.get('/accessrestrictions/',
                        response={200: list[AccessRestrictionSchema], **auth_responses},
                        summary="Get access restriction list")
@paginate
def accessrestriction_list(request):
    # todo cache?
    return mapdata_list_endpoint(request, model=AccessRestriction)


@mapdata_api_router.get('/accessrestrictions/{accessrestriction_id}/',
                        response={200: AccessRestrictionSchema, **API404.dict(), **auth_responses},
                        summary="Get access restriction by ID")
def accessrestriction_by_id(request, accessrestriction_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, AccessRestriction, pk=accessrestriction_id)


"""
AccessRestrictionGroups
"""


@mapdata_api_router.get('/accessrestrictiongroups/',
                        response={200: list[AccessRestrictionGroupSchema], **auth_responses},
                        summary="Get access restriction group list")
@paginate
def accessrestrictiongroup_list(request):
    # todo cache?
    return mapdata_list_endpoint(request, model=AccessRestrictionGroup)


@mapdata_api_router.get('/accessrestrictiongroups/{group_id}/',
                        response={200: AccessRestrictionGroupSchema, **API404.dict(), **auth_responses},
                        summary="Get access restriction group by ID")
def accessrestrictiongroups_by_id(request, group_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, AccessRestrictionGroup, pk=group_id)


"""
DynamicLocations
"""


@mapdata_api_router.get('/dynamiclocations/',
                        response={200: list[DynamicLocationSchema], **auth_responses},
                        summary="Get dynamic location list")
@paginate
def dynamiclocation_list(request):
    # todo cache?
    return mapdata_list_endpoint(request, model=DynamicLocation)


@mapdata_api_router.get('/dynamiclocations/{dynamiclocation_id}/',
                        response={200: DynamicLocationSchema, **API404.dict(), **auth_responses},
                        summary="Get dynamic location by ID")
def dynamiclocation_by_id(request, dynamiclocation_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, DynamicLocation, pk=dynamiclocation_id)
