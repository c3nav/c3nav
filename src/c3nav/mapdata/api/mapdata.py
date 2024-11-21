from typing import Optional, Sequence, Type

from django.db.models import Model
from ninja import Query
from ninja import Router as APIRouter

from c3nav.api.auth import auth_responses, validate_responses
from c3nav.api.exceptions import API404
from c3nav.mapdata.api.base import api_etag, optimize_query
from c3nav.mapdata.models import (Area, Building, Door, Hole, Level, LocationGroup, LocationGroupCategory, Source,
                                  Space, Stair, DataOverlay, DataOverlayFeature)
from c3nav.mapdata.models.access import AccessRestriction, AccessRestrictionGroup
from c3nav.mapdata.models.geometry.space import (POI, Column, CrossDescription, LeaveDescription, LineObstacle,
                                                 Obstacle, Ramp)
from c3nav.mapdata.models.locations import DynamicLocation
from c3nav.mapdata.schemas.filters import (ByCategoryFilter, ByGroupFilter, ByOnTopOfFilter, FilterSchema,
                                           LevelGeometryFilter, SpaceGeometryFilter)
from c3nav.mapdata.schemas.model_base import schema_description
from c3nav.mapdata.schemas.models import (AccessRestrictionGroupSchema, AccessRestrictionSchema, AreaSchema,
                                          BuildingSchema, ColumnSchema, CrossDescriptionSchema, DoorSchema,
                                          DynamicLocationSchema, HoleSchema, LeaveDescriptionSchema, LevelSchema,
                                          LineObstacleSchema, LocationGroupCategorySchema, LocationGroupSchema,
                                          ObstacleSchema, POISchema, RampSchema, SourceSchema, SpaceSchema, StairSchema,
                                          DataOverlaySchema, DataOverlayFeatureSchema)

mapdata_api_router = APIRouter(tags=["mapdata"])


def mapdata_list_endpoint(request,
                          model: Type[Model],
                          filters: Optional[FilterSchema] = None,
                          order_by: Sequence[str] = ('pk',)):
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


@mapdata_api_router.get('/levels/', summary="level list",
                        tags=["mapdata-root"], description=schema_description(LevelSchema),
                        response={200: list[LevelSchema], **validate_responses, **auth_responses})
@api_etag()
def level_list(request, filters: Query[LevelFilters]):
    return mapdata_list_endpoint(request, model=Level, filters=filters)


@mapdata_api_router.get('/levels/{level_id}/', summary="level by ID",
                        tags=["mapdata-root"], description=schema_description(LevelSchema),
                        response={200: LevelSchema, **API404.dict(), **auth_responses})
@api_etag()
def level_by_id(request, level_id: int):
    return mapdata_retrieve_endpoint(request, Level, pk=level_id)


"""
Buildings
"""


@mapdata_api_router.get('/buildings/', summary="building list",
                        tags=["mapdata-level"], description=schema_description(BuildingSchema),
                        response={200: list[BuildingSchema], **validate_responses, **auth_responses})
@api_etag(base_mapdata=True)
def building_list(request, filters: Query[LevelGeometryFilter]):
    return mapdata_list_endpoint(request, model=Building, filters=filters)


@mapdata_api_router.get('/buildings/{building_id}/', summary="building by ID",
                        tags=["mapdata-level"], description=schema_description(BuildingSchema),
                        response={200: BuildingSchema, **API404.dict(), **auth_responses})
@api_etag(base_mapdata=True)
def building_by_id(request, building_id: int):
    return mapdata_retrieve_endpoint(request, Building, pk=building_id)


"""
Spaces
"""


class SpaceFilters(ByGroupFilter, LevelGeometryFilter):
    pass


@mapdata_api_router.get('/spaces/', summary="space list",
                        tags=["mapdata-level"], description=schema_description(SpaceSchema),
                        response={200: list[SpaceSchema], **validate_responses, **auth_responses})
@api_etag(base_mapdata=True)
def space_list(request, filters: Query[SpaceFilters]):
    return mapdata_list_endpoint(request, model=Space, filters=filters)


@mapdata_api_router.get('/space/{space_id}/', summary="space by ID",
                        tags=["mapdata-level"], description=schema_description(SpaceSchema),
                        response={200: SpaceSchema, **API404.dict(), **auth_responses})
@api_etag(base_mapdata=True)
def space_by_id(request, space_id: int):
    return mapdata_retrieve_endpoint(request, Space, pk=space_id)


"""
Doors
"""


@mapdata_api_router.get('/doors/', summary="door list",
                        tags=["mapdata-level"], description=schema_description(DoorSchema),
                        response={200: list[DoorSchema], **validate_responses, **auth_responses})
@api_etag(base_mapdata=True)
def door_list(request, filters: Query[LevelGeometryFilter]):
    return mapdata_list_endpoint(request, model=Door, filters=filters)


@mapdata_api_router.get('/doors/{door_id}/', summary="door by ID",
                        tags=["mapdata-level"], description=schema_description(DoorSchema),
                        response={200: DoorSchema, **API404.dict(), **auth_responses})
@api_etag(base_mapdata=True)
def door_by_id(request, door_id: int):
    return mapdata_retrieve_endpoint(request, Door, pk=door_id)


"""
Holes
"""


@mapdata_api_router.get('/holes/', summary="hole list",
                        tags=["mapdata-space"], description=schema_description(HoleSchema),
                        response={200: list[HoleSchema], **validate_responses, **auth_responses})
@api_etag()
def hole_list(request, filters: Query[SpaceGeometryFilter]):
    return mapdata_list_endpoint(request, model=Hole, filters=filters)


@mapdata_api_router.get('/holes/{hole_id}/', summary="hole by ID",
                        tags=["mapdata-space"], description=schema_description(HoleSchema),
                        response={200: HoleSchema, **API404.dict(), **auth_responses})
@api_etag()
def hole_by_id(request, hole_id: int):
    return mapdata_retrieve_endpoint(request, Hole, pk=hole_id)


"""
Areas
"""


class AreaFilters(ByGroupFilter, SpaceGeometryFilter):
    pass


@mapdata_api_router.get('/areas/', summary="area list",
                        tags=["mapdata-space"], description=schema_description(AreaSchema),
                        response={200: list[AreaSchema], **validate_responses, **auth_responses})
@api_etag()
def area_list(request, filters: Query[AreaFilters]):
    return mapdata_list_endpoint(request, model=Area, filters=filters)


@mapdata_api_router.get('/areas/{area_id}/', summary="area by ID",
                        tags=["mapdata-space"], description=schema_description(AreaSchema),
                        response={200: AreaSchema, **API404.dict(), **auth_responses})
@api_etag()
def area_by_id(request, area_id: int):
    return mapdata_retrieve_endpoint(request, Area, pk=area_id)


"""
Stairs
"""


@mapdata_api_router.get('/stairs/', summary="stair list",
                        tags=["mapdata-space"], description=schema_description(StairSchema),
                        response={200: list[StairSchema], **validate_responses, **auth_responses})
@api_etag()
def stair_list(request, filters: Query[SpaceGeometryFilter]):
    return mapdata_list_endpoint(request, model=Stair, filters=filters)


@mapdata_api_router.get('/stairs/{stair_id}/', summary="stair by ID",
                        tags=["mapdata-space"], description=schema_description(StairSchema),
                        response={200: StairSchema, **API404.dict(), **auth_responses})
@api_etag()
def stair_by_id(request, stair_id: int):
    return mapdata_retrieve_endpoint(request, Stair, pk=stair_id)


"""
Ramps
"""


@mapdata_api_router.get('/ramps/', summary="ramp list",
                        tags=["mapdata-space"], description=schema_description(RampSchema),
                        response={200: list[RampSchema], **validate_responses, **auth_responses})
@api_etag()
def ramp_list(request, filters: Query[SpaceGeometryFilter]):
    return mapdata_list_endpoint(request, model=Ramp, filters=filters)


@mapdata_api_router.get('/ramps/{ramp_id}/', summary="ramp by ID",
                        tags=["mapdata-space"], description=schema_description(RampSchema),
                        response={200: RampSchema, **API404.dict(), **auth_responses})
@api_etag()
def ramp_by_id(request, ramp_id: int):
    return mapdata_retrieve_endpoint(request, Ramp, pk=ramp_id)


"""
Obstacles
"""


@mapdata_api_router.get('/obstacles/', summary="obstacle list",
                        tags=["mapdata-space"], description=schema_description(ObstacleSchema),
                        response={200: list[ObstacleSchema], **validate_responses, **auth_responses})
@api_etag()
def obstacle_list(request, filters: Query[SpaceGeometryFilter]):
    return mapdata_list_endpoint(request, model=Obstacle, filters=filters)


@mapdata_api_router.get('/obstacles/{obstacle_id}/', summary="obstacle by ID",
                        tags=["mapdata-space"], description=schema_description(ObstacleSchema),
                        response={200: ObstacleSchema, **API404.dict(), **auth_responses})
@api_etag()
def obstacle_by_id(request, obstacle_id: int):
    return mapdata_retrieve_endpoint(request, Obstacle, pk=obstacle_id)


"""
LineObstacles
"""


@mapdata_api_router.get('/lineobstacles/', summary="line obstacle list",
                        tags=["mapdata-space"], description=schema_description(LineObstacleSchema),
                        response={200: list[LineObstacleSchema], **validate_responses, **auth_responses})
@api_etag()
def lineobstacle_list(request, filters: Query[SpaceGeometryFilter]):
    return mapdata_list_endpoint(request, model=LineObstacle, filters=filters)


@mapdata_api_router.get('/lineobstacles/{lineobstacle_id}/', summary="line obstacle by ID",
                        tags=["mapdata-space"], description=schema_description(LineObstacleSchema),
                        response={200: LineObstacleSchema, **API404.dict(), **auth_responses},)
@api_etag()
def lineobstacle_by_id(request, lineobstacle_id: int):
    return mapdata_retrieve_endpoint(request, LineObstacle, pk=lineobstacle_id)


"""
Columns
"""


@mapdata_api_router.get('/columns/', summary="column list",
                        tags=["mapdata-space"], description=schema_description(ColumnSchema),
                        response={200: list[ColumnSchema], **validate_responses, **auth_responses})
@api_etag()
def column_list(request, filters: Query[SpaceGeometryFilter]):
    return mapdata_list_endpoint(request, model=Column, filters=filters)


@mapdata_api_router.get('/columns/{column_id}/', summary="column by ID",
                        tags=["mapdata-space"], description=schema_description(ColumnSchema),
                        response={200: ColumnSchema, **API404.dict(), **auth_responses})
@api_etag()
def column_by_id(request, column_id: int):
    return mapdata_retrieve_endpoint(request, Column, pk=column_id)


"""
POIs
"""


@mapdata_api_router.get('/pois/', summary="POI list",
                        tags=["mapdata-space"], description=schema_description(POISchema),
                        response={200: list[POISchema], **validate_responses, **auth_responses})
@api_etag()
def poi_list(request, filters: Query[SpaceGeometryFilter]):
    return mapdata_list_endpoint(request, model=POI, filters=filters)


@mapdata_api_router.get('/pois/{poi_id}/', summary="POI by ID",
                        tags=["mapdata-space"], description=schema_description(POISchema),
                        response={200: POISchema, **API404.dict(), **auth_responses})
@api_etag()
def poi_by_id(request, poi_id: int):
    return mapdata_retrieve_endpoint(request, POI, pk=poi_id)


"""
LeaveDescriptions
"""


@mapdata_api_router.get('/leavedescriptions/', summary="leave description list",
                        tags=["mapdata-space"], description=schema_description(LeaveDescriptionSchema),
                        response={200: list[LeaveDescriptionSchema], **validate_responses, **auth_responses})
@api_etag()
def leavedescription_list(request, filters: Query[SpaceGeometryFilter]):
    return mapdata_list_endpoint(request, model=LeaveDescription, filters=filters)


@mapdata_api_router.get('/leavedescriptions/{leavedescription_id}/', summary="leave description by ID",
                        tags=["mapdata-space"], description=schema_description(LeaveDescriptionSchema),
                        response={200: LeaveDescriptionSchema, **API404.dict(), **auth_responses})
@api_etag()
def leavedescription_by_id(request, leavedescription_id: int):
    return mapdata_retrieve_endpoint(request, LeaveDescription, pk=leavedescription_id)


"""
CrossDescriptions
"""


@mapdata_api_router.get('/crossdescriptions/', summary="cross description list",
                        tags=["mapdata-space"], description=schema_description(CrossDescriptionSchema),
                        response={200: list[CrossDescriptionSchema], **validate_responses, **auth_responses})
@api_etag()
def crossdescription_list(request, filters: Query[SpaceGeometryFilter]):
    return mapdata_list_endpoint(request, model=CrossDescription, filters=filters)


@mapdata_api_router.get('/crossdescriptions/{crossdescription_id}/', summary="cross description by ID",
                        tags=["mapdata-space"], description=schema_description(CrossDescriptionSchema),
                        response={200: CrossDescriptionSchema, **API404.dict(), **auth_responses})
@api_etag()
def crossdescription_by_id(request, crossdescription_id: int):
    return mapdata_retrieve_endpoint(request, CrossDescription, pk=crossdescription_id)


"""
LocationGroup
"""


@mapdata_api_router.get('/locationgroups/', summary="location group list",
                        tags=["mapdata-root"], description=schema_description(LocationGroupSchema),
                        response={200: list[LocationGroupSchema], **validate_responses, **auth_responses})
@api_etag()
def locationgroup_list(request, filters: Query[ByCategoryFilter]):
    return mapdata_list_endpoint(request, model=LocationGroup, filters=filters)


@mapdata_api_router.get('/locationgroups/{locationgroup_id}/', summary="location group by ID",
                        tags=["mapdata-root"], description=schema_description(LocationGroupSchema),
                        response={200: LocationGroupSchema, **API404.dict(), **auth_responses})
@api_etag()
def locationgroup_by_id(request, locationgroup_id: int):
    return mapdata_retrieve_endpoint(request, LocationGroup, pk=locationgroup_id)


"""
LocationGroupCategories
"""


@mapdata_api_router.get('/locationgroupcategories/', summary="location group category list",
                        tags=["mapdata-root"], description=schema_description(LocationGroupCategorySchema),
                        response={200: list[LocationGroupCategorySchema], **auth_responses})
@api_etag()
def locationgroupcategory_list(request):
    return mapdata_list_endpoint(request, model=LocationGroupCategory)


@mapdata_api_router.get('/locationgroupcategories/{category_id}/', summary="location group category by ID",
                        tags=["mapdata-root"], description=schema_description(LocationGroupCategorySchema),
                        response={200: LocationGroupCategorySchema, **API404.dict(), **auth_responses})
@api_etag()
def locationgroupcategory_by_id(request, category_id: int):
    return mapdata_retrieve_endpoint(request, LocationGroupCategory, pk=category_id)


"""
Sources
"""


@mapdata_api_router.get('/sources/', summary="source list",
                        tags=["mapdata-root"], description=schema_description(SourceSchema),
                        response={200: list[SourceSchema], **auth_responses})
@api_etag()
def source_list(request):
    return mapdata_list_endpoint(request, model=Source)


@mapdata_api_router.get('/sources/{source_id}/', summary="source by ID",
                        tags=["mapdata-root"], description=schema_description(SourceSchema),
                        response={200: SourceSchema, **API404.dict(), **auth_responses})
@api_etag()
def source_by_id(request, source_id: int):
    return mapdata_retrieve_endpoint(request, Source, pk=source_id)


"""
AccessRestrictions
"""


@mapdata_api_router.get('/accessrestrictions/', summary="access restriction list",
                        tags=["mapdata-root"], description=schema_description(AccessRestrictionSchema),
                        response={200: list[AccessRestrictionSchema], **auth_responses})
@api_etag()
def accessrestriction_list(request):
    return mapdata_list_endpoint(request, model=AccessRestriction)


@mapdata_api_router.get('/accessrestrictions/{accessrestriction_id}/', summary="access restriction by ID",
                        tags=["mapdata-root"], description=schema_description(AccessRestrictionSchema),
                        response={200: AccessRestrictionSchema, **API404.dict(), **auth_responses})
@api_etag()
def accessrestriction_by_id(request, accessrestriction_id: int):
    return mapdata_retrieve_endpoint(request, AccessRestriction, pk=accessrestriction_id)


"""
AccessRestrictionGroups
"""


@mapdata_api_router.get('/accessrestrictiongroups/', summary="access restriction group list",
                        tags=["mapdata-root"], description=schema_description(AccessRestrictionGroupSchema),
                        response={200: list[AccessRestrictionGroupSchema], **auth_responses})
@api_etag()
def accessrestrictiongroup_list(request):
    return mapdata_list_endpoint(request, model=AccessRestrictionGroup)


@mapdata_api_router.get('/accessrestrictiongroups/{group_id}/', summary="access restriction group by ID",
                        tags=["mapdata-root"], description=schema_description(AccessRestrictionGroupSchema),
                        response={200: AccessRestrictionGroupSchema, **API404.dict(), **auth_responses})
@api_etag()
def accessrestrictiongroups_by_id(request, group_id: int):
    return mapdata_retrieve_endpoint(request, AccessRestrictionGroup, pk=group_id)


"""
DynamicLocations
"""


@mapdata_api_router.get('/dynamiclocations/', summary="dynamic location list",
                        tags=["mapdata-root"], description=schema_description(DynamicLocationSchema),
                        response={200: list[DynamicLocationSchema], **auth_responses})
@api_etag()
def dynamiclocation_list(request):
    return mapdata_list_endpoint(request, model=DynamicLocation)


@mapdata_api_router.get('/dynamiclocations/{dynamiclocation_id}/', summary="dynamic location by ID",
                        tags=["mapdata-root"], description=schema_description(DynamicLocationSchema),
                        response={200: DynamicLocationSchema, **API404.dict(), **auth_responses})
@api_etag()
def dynamiclocation_by_id(request, dynamiclocation_id: int):
    return mapdata_retrieve_endpoint(request, DynamicLocation, pk=dynamiclocation_id)


"""
Data overlays
"""


@mapdata_api_router.get('/overlays/', summary="data overlay list",
                        tags=["mapdata-root"], description=schema_description(DynamicLocationSchema),
                        response={200: list[DataOverlaySchema], **auth_responses})
@api_etag()
def dataoverlay_list(request):
    return mapdata_list_endpoint(request, model=DataOverlay)


@mapdata_api_router.get('/overlays/{overlay_id}/', summary="features for overlay by overlay ID",
                        tags=["mapdata-root"], description=schema_description(DynamicLocationSchema),
                        response={200: list[DataOverlayFeatureSchema], **API404.dict(), **auth_responses})
# @api_etag()
def dataoverlay_by_id(request, overlay_id: int):
    qs = optimize_query(
        DataOverlayFeature.qs_for_request(request)
    )

    qs = qs.filter(overlay_id=overlay_id)

    # order_by
    qs = qs.order_by('pk')

    return qs
