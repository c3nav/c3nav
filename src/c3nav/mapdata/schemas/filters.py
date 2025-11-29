from dataclasses import dataclass
from typing import Literal, Optional, Type, Annotated

from django.db.models import Model, QuerySet
from django.db.models.query_utils import Q
from pydantic import Field as APIField, AfterValidator

from c3nav.api.schema import BaseSchema
from c3nav.mapdata.models import Level, MapUpdate, Space, DataOverlay
from c3nav.mapdata.models.locations import LocationTag
from c3nav.mapdata.permissions import active_map_permissions
from c3nav.mapdata.utils.cache.proxied import versioned_cache


@dataclass
class ValidateID:
    model: Type[Model]

    @classmethod
    def _get_ids_for_model(cls) -> frozenset[int]:
        # todo: cache this locally, better, maybe lazily?
        # todo: this needs correct caching by permissions … which might be determined by processupdates
        cache_key = (
            f"mapdata:api:pks:{cls.model.__name__}"
            + (f":{active_map_permissions.permissions_cache_key}" if hasattr(cls.model, 'q_for_permissions') else "")
        )

        result = versioned_cache.get(MapUpdate.last_update(), cache_key, None)
        if result is not None:
            return result

        result = frozenset(cls.model.objects.values_list("id", flat=True))
        versioned_cache.set(MapUpdate.last_update(), cache_key, result, 300)

        return result

    def __call__(self, value: Optional[int]):
        return not (isinstance(value, int) and value in self._get_ids_for_model())


class FilterSchema(BaseSchema):
    def filter_qs(self, request, qs: QuerySet) -> QuerySet:
        return qs


class ByLevelFilter(FilterSchema):
    # todo: if level is calculated by processupdates, the endpoint should probably not answer for a while
    level: Annotated[Optional[int], AfterValidator(ValidateID(Level)), APIField(
        title="filter by level",
        description="if set, only items belonging to the level with this ID will be shown"
    )] = None

    def filter_qs(self, request, qs: QuerySet) -> QuerySet:
        if self.level is not None:
            qs = qs.filter(level_id=self.level)
        return super().filter_qs(request, qs)


class BySpaceFilter(FilterSchema):
    space: Annotated[Optional[int], AfterValidator(ValidateID(Space)), APIField(
        title="filter by space",
        description="if set, only items belonging to the space with this ID will be shown"
    )] = None

    def filter_qs(self, request, qs: QuerySet) -> QuerySet:
        if self.space is not None:
            qs = qs.filter(groups=self.space)
        return super().filter_qs(request, qs)


class TargetsByLocationFilter(FilterSchema):
    tag: Annotated[Optional[int], AfterValidator(ValidateID(LocationTag)), APIField(
        title="filter by location tag",
        description="if set, only items belonging to the location tag with this ID or one if its descendants will be shown"
    )] = None
    direct_location: Annotated[Optional[int], AfterValidator(ValidateID(LocationTag)), APIField(
        title="filter by direct location",
        description="if set, only items directly belonging to the location with this ID will be shown"
    )] = None

    def filter_qs(self, request, qs: QuerySet) -> QuerySet:
        if self.direct_location:
            qs = qs.filter(locations=self.direct_location)
        if self.tag:
            # todo: this is an additional query, would be nice to avoid that
            qs = qs.filter(tags__in=(*self.tag, LocationTag.objects.get(pk=self.tag).descendants))
        return super().filter_qs(request, qs)


class ByOnTopOfFilter(FilterSchema):
    on_top_of: Annotated[Optional[Literal["null"] | int], AfterValidator(ValidateID(Level)), APIField(
        title='filter by on top of level ID (or "null")',
        description='if set, only levels on top of the level with this ID (or "null" for no level) will be shown'
    )] = None

    def filter_qs(self, request, qs: QuerySet) -> QuerySet:
        if self.on_top_of is not None:
            qs = qs.filter(on_top_of_id=None if self.on_top_of == "null" else self.on_top_of)
        return super().filter_qs(request, qs)


class ByOverlayFilter(FilterSchema):
    overlay: Annotated[int, AfterValidator(ValidateID(DataOverlay)), APIField(
        title='filter by data overlay',
        description='only show overlay features belonging to this overlay'
    )] = None

    def filter_qs(self, request, qs: QuerySet) -> QuerySet:
        if self.overlay is not None:
            qs = qs.filter(overlay=self.overlay)
        return super().filter_qs(request, qs)


class RemoveGeometryFilter(FilterSchema):
    geometry: bool = APIField(
        False,
        title='include geometry',
        description='by default, geometry will be ommited. set to true to include it (if available)'
    )

    # todo: validated true as invalid if not avaiilable for this model

    def filter_qs(self, request, qs: QuerySet) -> QuerySet:
        if not self.geometry:
            qs = qs.defer('geometry')
        return super().filter_qs(request, qs)


class LevelGeometryFilter(ByLevelFilter, RemoveGeometryFilter):
    pass


class SpaceGeometryFilter(BySpaceFilter, RemoveGeometryFilter):
    pass
