from typing import Literal, Optional, Type

from django.core.cache import cache
from django.db.models import Model, QuerySet
from ninja import Schema
from pydantic import Field as APIField

from c3nav.api.exceptions import APIRequestValidationFailed
from c3nav.mapdata.models import Level, LocationGroup, MapUpdate
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


class FilterSchema(Schema):
    def filter_qs(self, qs: QuerySet) -> QuerySet:
        return qs

    def validate(self, request):
        pass


class GroupFilter(FilterSchema):
    group: Optional[int] = APIField(
        None,
        title="filter by location group",
        description="if set, only items belonging to the location group with that ID will be shown"
    )

    def validate(self, request):
        super().validate(request)
        if self.group is not None:
            assert_valid_value(request, LocationGroup, "pk", {self.group})

    def filter_qs(self, qs: QuerySet) -> QuerySet:
        qs = super().filter_qs(qs)
        if self.group is not None:
            qs = qs.filter(groups=self.group)
        return super().filter_qs(qs)


class OnTopOfFilter(FilterSchema):
    on_top_of: Optional[Literal["null"] | int] = APIField(
        None,
        title='filter by on top of level ID (or "null")',
        description='if set, only levels on top of the level with this ID (or "null" for no level) will be shown'
    )

    def validate(self, request):
        super().validate(request)
        if self.group is not None and self.group != "null":
            assert_valid_value(request, Level, "pk", {self.on_top_of})

    def filter_qs(self, qs: QuerySet) -> QuerySet:
        if self.on_top_of is not None:
            qs = qs.filter(on_top_of_id=None if self.on_top_of == "null" else self.on_top_of)
        return super().filter_qs(qs)
