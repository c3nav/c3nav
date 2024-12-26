from dataclasses import dataclass
from typing import Optional, Sequence, Type, Callable, Any

from django.db import transaction
from django.db.models import Model, F
from django.shortcuts import get_object_or_404
from ninja import Query
from ninja import Router as APIRouter
from pydantic import PositiveInt

from c3nav.api.auth import auth_responses, validate_responses, auth_permission_responses
from c3nav.api.exceptions import API404, APIPermissionDenied
from c3nav.api.schema import BaseSchema
from c3nav.mapdata.api.base import api_etag, optimize_query, can_access_geometry
from c3nav.mapdata.models import (Area, Building, Door, Hole, Level, LocationGroup, LocationGroupCategory, Source,
                                  Space, Stair, DataOverlay, DataOverlayFeature, WayType)
from c3nav.mapdata.models.access import AccessRestriction, AccessRestrictionGroup, AccessPermission
from c3nav.mapdata.models.geometry.space import (POI, Column, CrossDescription, LeaveDescription, LineObstacle,
                                                 Obstacle, Ramp)
from c3nav.mapdata.models.locations import DynamicLocation, LabelSettings, LocationRedirect
from c3nav.mapdata.schemas.filters import (ByCategoryFilter, ByGroupFilter, ByOnTopOfFilter, FilterSchema,
                                           LevelGeometryFilter, SpaceGeometryFilter, BySpaceFilter, ByOverlayFilter)
from c3nav.mapdata.schemas.model_base import schema_description, LabelSettingsSchema
from c3nav.mapdata.schemas.models import (AccessRestrictionGroupSchema, AccessRestrictionSchema, AreaSchema,
                                          BuildingSchema, ColumnSchema, CrossDescriptionSchema, DoorSchema,
                                          DynamicLocationSchema, HoleSchema, LeaveDescriptionSchema, LevelSchema,
                                          LineObstacleSchema, LocationGroupCategorySchema, LocationGroupSchema,
                                          ObstacleSchema, POISchema, RampSchema, SourceSchema, SpaceSchema, StairSchema,
                                          DataOverlaySchema, DataOverlayFeatureSchema, LocationRedirectSchema,
                                          WayTypeSchema, DataOverlayFeatureGeometrySchema,
                                          DataOverlayFeatureUpdateSchema, DataOverlayFeatureBulkUpdateSchema,
                                          )

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
        qs = filters.filter_qs(request, qs)

    # order_by
    qs = qs.order_by(*order_by)

    result = list(qs)

    for obj in result:
        if not can_access_geometry(request, obj):
            obj._hide_geometry = True

    return result


def mapdata_retrieve_endpoint(request, model: Type[Model], **lookups):
    try:
        obj = optimize_query(
            model.qs_for_request(request) if hasattr(model, 'qs_for_request') else model.objects.all()
        ).get(**lookups)
        if not can_access_geometry(request, obj):
            obj.geometry = None
        return obj
    except model.DoesNotExist:
        raise API404("%s not found" % model.__name__.lower())


@dataclass
class MapdataEndpoint:
    model: Type[Model]
    schema: Type[BaseSchema]
    filters: Type[FilterSchema] | None = None
    no_cache: bool = False
    name: Optional[str] = None

    @property
    def model_name(self):
        return self.model._meta.model_name

    @property
    def endpoint_name(self):
        return self.name if self.name is not None else self.model._meta.default_related_name


@dataclass
class MapdataAPIBuilder:
    router: APIRouter

    def build_all_endpoints(self, endpoints: dict[str, list[MapdataEndpoint]]):
        for tag, endpoints in endpoints.items():
            for endpoint in endpoints:
                self.add_endpoints(endpoint, tag=tag)

    def add_endpoints(self, endpoint: MapdataEndpoint, tag: str):
        self.add_list_endpoint(endpoint, tag=tag)
        self.add_by_id_endpoint(endpoint, tag=tag)

    def common_params(self, endpoint: MapdataEndpoint) -> dict[str: Any]:
        return {"request": None}

    def _make_endpoint(self, view_params: dict[str, str], call_func: Callable,
                       add_call_params: dict[str, str] = None) -> Callable:

        if add_call_params is None:
            add_call_params = {}
        call_param_values = set(add_call_params.values())
        call_params = (
            *(f"{name}={name}" for name in set(view_params.keys()) - call_param_values),
            *(f"{name}={value}" for name, value in add_call_params.items()),
        )
        method_code = "\n".join((
            f"def gen_func({", ".join((f"{name}: {hint}" if hint else name) for name, hint in view_params.items())}):",
            f"    return call_func({", ".join(call_params)})",
        ))
        g = {
            **globals(),
            "call_func": call_func,
        }
        exec(method_code, g)
        return g["gen_func"]  # noqa

    def add_list_endpoint(self, endpoint: MapdataEndpoint, tag: str):
        view_params = self.common_params(endpoint)

        Query  # noqa
        if endpoint.filters:
            filters_name = endpoint.filters.__name__
            view_params["filters"] = f"Query[{filters_name}]"

        list_func = self._make_endpoint(
            view_params=view_params,
            call_func=mapdata_list_endpoint,
            add_call_params={"model": endpoint.model.__name__}
        )
        list_func.__name__ = f"{endpoint.model_name}_list"

        if not endpoint.no_cache:
            list_func = api_etag()(list_func)

        self.router.get(f"/{endpoint.endpoint_name}/", summary=f"{endpoint.model_name} list",
                        tags=[f"mapdata-{tag}"], description=schema_description(endpoint.schema),
                        response={200: list[endpoint.schema],
                                  **(validate_responses if endpoint.filters else {}),
                                  **auth_responses})(
            list_func
        )

    def add_by_id_endpoint(self, endpoint: MapdataEndpoint, tag: str):
        view_params = self.common_params(endpoint)
        PositiveInt  # noqa
        id_field = f"{endpoint.model_name}_id"
        view_params[id_field] = "PositiveInt"

        list_func = self._make_endpoint(
            view_params=view_params,
            call_func=mapdata_retrieve_endpoint,
            add_call_params={"model": endpoint.model.__name__, "pk": id_field}
        )
        list_func.__name__ = f"{endpoint.model_name}_by_id"

        self.router.get(f'/{endpoint.endpoint_name}/{{{id_field}}}/', summary=f"{endpoint.model_name} by ID",
                        tags=[f"mapdata-{tag}"], description=schema_description(endpoint.schema),
                        response={200: endpoint.schema, **API404.dict(), **auth_responses})(
            api_etag()(list_func)
        )


class LevelFilters(ByGroupFilter, ByOnTopOfFilter):
    pass


class SpaceFilters(ByGroupFilter, LevelGeometryFilter):
    pass


class AreaFilters(ByGroupFilter, SpaceGeometryFilter):
    pass


mapdata_endpoints: dict[str, list[MapdataEndpoint]] = {
    "root": [
        MapdataEndpoint(
            model=Level,
            schema=LevelSchema,
            filters=LevelFilters
        ),
        MapdataEndpoint(
            model=LocationGroup,
            schema=LocationGroupSchema,
            filters=ByCategoryFilter,
        ),
        MapdataEndpoint(
            model=LocationGroupCategory,
            schema=LocationGroupCategorySchema,
        ),
        MapdataEndpoint(
            model=LocationRedirect,
            schema=LocationRedirectSchema,
        ),
        MapdataEndpoint(
            model=Source,
            schema=SourceSchema,
        ),
        MapdataEndpoint(
            model=AccessRestriction,
            schema=AccessRestrictionSchema,
        ),
        MapdataEndpoint(
            model=AccessRestrictionGroup,
            schema=AccessRestrictionGroupSchema,
        ),
        MapdataEndpoint(
            model=DynamicLocation,
            schema=DynamicLocationSchema,
        ),
        MapdataEndpoint(
            model=LabelSettings,
            schema=LabelSettingsSchema,
        ),
        MapdataEndpoint(
            model=DataOverlay,
            schema=DataOverlaySchema,
        ),
        MapdataEndpoint(
            model=DataOverlayFeature,
            schema=DataOverlayFeatureSchema,
            filters=ByOverlayFilter,
            no_cache=True,
        ),
        MapdataEndpoint(
            model=DataOverlayFeature,
            schema=DataOverlayFeatureGeometrySchema,
            filters=ByOverlayFilter,
            no_cache=True,
            name='dataoverlayfeaturegeometries'
        ),
        MapdataEndpoint(
            model=WayType,
            schema=WayTypeSchema,
        ),
    ],
    "level": [
        MapdataEndpoint(
            model=Building,
            schema=BuildingSchema,
            filters=LevelGeometryFilter
        ),
        MapdataEndpoint(
            model=Space,
            schema=SpaceSchema,
            filters=SpaceFilters,
        ),
        MapdataEndpoint(
            model=Door,
            schema=DoorSchema,
            filters=LevelGeometryFilter,
        )
    ],
    "space": [
        MapdataEndpoint(
            model=Hole,
            schema=HoleSchema,
            filters=SpaceGeometryFilter,
        ),
        MapdataEndpoint(
            model=Area,
            schema=AreaSchema,
            filters=AreaFilters,
        ),
        MapdataEndpoint(
            model=Stair,
            schema=StairSchema,
            filters=SpaceGeometryFilter,
        ),
        MapdataEndpoint(
            model=Ramp,
            schema=RampSchema,
            filters=SpaceGeometryFilter,
        ),
        MapdataEndpoint(
            model=Obstacle,
            schema=ObstacleSchema,
            filters=SpaceGeometryFilter,
        ),
        MapdataEndpoint(
            model=LineObstacle,
            schema=LineObstacleSchema,
            filters=SpaceGeometryFilter,
        ),
        MapdataEndpoint(
            model=Column,
            schema=ColumnSchema,
            filters=SpaceGeometryFilter,
        ),
        MapdataEndpoint(
            model=POI,
            schema=POISchema,
            filters=SpaceGeometryFilter,
        ),
        MapdataEndpoint(
            model=LeaveDescription,
            schema=LeaveDescriptionSchema,
            filters=BySpaceFilter,
        ),
        MapdataEndpoint(
            model=CrossDescription,
            schema=CrossDescriptionSchema,
            filters=BySpaceFilter,
        ),
    ],
}

MapdataAPIBuilder(router=mapdata_api_router).build_all_endpoints(mapdata_endpoints)


@mapdata_api_router.post('/dataoverlayfeatures/{id}', summary="update a data overlay feature (including geometries)",
                         response={204: None, **API404.dict(), **auth_permission_responses})
def update_data_overlay_feature(request, id: int, parameters: DataOverlayFeatureUpdateSchema):
    """
    update the data overlay feature
    """

    feature = get_object_or_404(DataOverlayFeature, id=id)

    if feature.overlay.edit_access_restriction_id is None or feature.overlay.edit_access_restriction_id not in AccessPermission.get_for_request(
            request):
        raise APIPermissionDenied('You are not allowed to edit this object.')

    updates = parameters.dict(exclude_unset=True)

    for key, value in updates.items():
        setattr(feature, key, value)

    feature.save()

    return 204, None


@mapdata_api_router.post('/dataoverlayfeatures-bulk', summary="bulk-update data overlays (including geometries)",
                         response={204: None, **API404.dict(), **auth_permission_responses})
def update_data_overlay_features_bulk(request, parameters: DataOverlayFeatureBulkUpdateSchema):
    permissions = AccessPermission.get_for_request(request)

    updates = {
        u.id: u
        for u in parameters.updates
    }

    forbidden_object_ids = []

    with transaction.atomic():
        features = DataOverlayFeature.objects.filter(id__in=updates.keys()).annotate(
            edit_access_restriction_id=F('overlay__edit_access_restriction_id'))

        for feature in features:
            if feature.edit_access_restriction_id is None or feature.edit_access_restriction_id not in permissions:
                forbidden_object_ids.append(feature.id)
                continue

            changes = updates[feature.id].dict(exclude_unset=True)

            for key, value in changes.items():
                if key == 'id':
                    continue
                setattr(feature, key, value)
            feature.save()

        if len(forbidden_object_ids) > 0:
            raise APIPermissionDenied('You are not allowed to edit the objects with the following ids: %s.'
                                      % ", ".join([str(x) for x in forbidden_object_ids]))

    return 204, None
