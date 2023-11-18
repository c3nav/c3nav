from typing import Optional, Sequence, Type

from django.db.models import Model
from ninja import Query
from ninja import Router as APIRouter
from ninja.pagination import paginate

from c3nav.api.exceptions import API404
from c3nav.api.newauth import auth_responses
from c3nav.mapdata.api import optimize_query
from c3nav.mapdata.models import Level, Source
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.schemas.filters import FilterSchema, GroupFilter, OnTopOfFilter
from c3nav.mapdata.schemas.models import LevelSchema
from c3nav.mapdata.schemas.responses import BoundsSchema

map_api_router = APIRouter(tags=["map"])


@map_api_router.get('/bounds/', summary="Get map boundaries",
                    response={200: BoundsSchema, **auth_responses})
def bounds(request):
    return {
        "bounds": Source.max_bounds(),
    }


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


class LevelFilters(GroupFilter, OnTopOfFilter):
    pass


@map_api_router.get('/levels/', response=list[LevelSchema],
                    summary="Get level list")
@paginate
def levels_list(request, filters: Query[LevelFilters]):
    # todo cache?
    return mapdata_list_endpoint(request, model=Level, filters=filters)


@map_api_router.get('/levels/{level_id}/', response=LevelSchema,
                    summary="Get level by ID")
def level_detail(request, level_id: int):
    # todo: access, caching, filtering, etc
    return mapdata_retrieve_endpoint(request, Level, pk=level_id)
