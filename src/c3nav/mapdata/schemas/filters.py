from typing import Literal, Optional, Type

from django.core.cache import cache
from django.db.models import Model, QuerySet
from pydantic import Field as APIField

from c3nav.api.exceptions import APIRequestValidationFailed
from c3nav.api.schema import BaseSchema
from c3nav.mapdata.models import Level, LocationGroup, LocationGroupCategory, MapUpdate, Space, Door, Building
from c3nav.mapdata.models.access import AccessPermission


def get_keys_for_model(request, model: Type[Model], key: str) -> set:
    # get all accessible keys for this model for this request
    if hasattr(model, 'qs_for_request'):
        cache_key = 'mapdata:api:keys:%s:%s:%s' % (model.__name__, key,
                                                   AccessPermission.cache_key_for_request(request))
        qs = model.qs_for_request(request)
    else:
        cache_key = 'mapdata:api:keys:%s:%s:%s' % (model.__name__, key,
                                                   MapUpdate.current_cache_key())
        qs = model.objects.all()

    result = cache.get(cache_key, None)
    if result is not None:
        return result

    result = set(qs.values_list(key, flat=True))
    cache.set(cache_key, result, 300)

    return result


def assert_valid_value(request, model: Type[Model], key: str, values: set):
    keys = get_keys_for_model(request, model, key)
    remainder = values-keys
    if remainder:
        raise APIRequestValidationFailed("Unknown %s: %r" % (model.__name__, remainder))


class FilterSchema(BaseSchema):
    def filter_qs(self, request, qs: QuerySet) -> QuerySet:
        return qs

    def validate(self, request):
        pass


class ByLevelFilter(FilterSchema):
    level: Optional[int] = APIField(
        None,
        title="filter by level",
        description="if set, only items belonging to the level with this ID will be shown"
    )

    def validate(self, request):
        super().validate(request)
        if self.level is not None:
            assert_valid_value(request, Level, "pk", {self.level})

    def filter_qs(self, request, qs: QuerySet) -> QuerySet:
        if self.level is not None:
            qs = qs.filter(level_id=self.level)
        return super().filter_qs(request, qs)


class BySpaceFilter(FilterSchema):
    space: Optional[int] = APIField(
        None,
        title="filter by space",
        description="if set, only items belonging to the space with this ID will be shown"
    )

    def validate(self, request):
        super().validate(request)
        if self.space is not None:
            assert_valid_value(request, Space, "pk", {self.space})

    def filter_qs(self, request, qs: QuerySet) -> QuerySet:
        if self.space is not None:
            qs = qs.filter(groups=self.space)
        return super().filter_qs(request, qs)


class ByCategoryFilter(FilterSchema):
    category: Optional[int] = APIField(
        None,
        title="filter by location group category",
        description="if set, only groups belonging to the location group category with this ID will be shown"
    )

    def validate(self, request):
        super().validate(request)
        if self.category is not None:
            assert_valid_value(request, LocationGroupCategory, "pk", {self.category})

    def filter_qs(self, request, qs: QuerySet) -> QuerySet:
        if self.category is not None:
            qs = qs.filter(category=self.category)
        return super().filter_qs(request, qs)


class ByGroupFilter(FilterSchema):
    group: Optional[int] = APIField(
        None,
        title="filter by location group",
        description="if set, only items belonging to the location group with this ID will be shown"
    )

    def validate(self, request):
        super().validate(request)
        if self.group is not None:
            assert_valid_value(request, LocationGroup, "pk", {self.group})

    def filter_qs(self, request, qs: QuerySet) -> QuerySet:
        if self.group is not None:
            qs = qs.filter(groups=self.group)
        return super().filter_qs(request, qs)


class ByOnTopOfFilter(FilterSchema):
    on_top_of: Optional[Literal["null"] | int] = APIField(
        None,
        title='filter by on top of level ID (or "null")',
        description='if set, only levels on top of the level with this ID (or "null" for no level) will be shown'
    )

    def validate(self, request):
        super().validate(request)
        if self.group is not None and self.group != "null":
            assert_valid_value(request, Level, "pk", {self.on_top_of})

    def filter_qs(self, request, qs: QuerySet) -> QuerySet:
        if self.on_top_of is not None:
            qs = qs.filter(on_top_of_id=None if self.on_top_of == "null" else self.on_top_of)
        return super().filter_qs(request, qs)


class ByOverlayFilter(FilterSchema):
    overlay: int = APIField(
        title='filter by data overlay',
        description='only show overlay features belonging to this overlay'
    )

    def validate(self, request):
        super().validate(request)
        if self.overlay is not None:
            assert_valid_value(request, Level, "pk", {self.overlay})

    def filter_qs(self, request, qs: QuerySet) -> QuerySet:
        if self.overlay is not None:
            qs = qs.filter(overlay=self.overlay)
        return super().filter_qs(request, qs)


class BySearchableFilter(FilterSchema):
    searchable: bool = APIField(
        False,
        title='searchable locations only',
        description='only show locations that should show up in search'
    )

    def filter_qs(self, request, qs: QuerySet) -> QuerySet:
        if self.searchable is not None:
            qs = qs.filter(can_search=True)
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
