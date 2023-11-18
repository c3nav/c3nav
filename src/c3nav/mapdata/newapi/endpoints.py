from ninja import Query
from ninja import Router as APIRouter
from ninja.pagination import paginate

from c3nav.api.exceptions import API404
from c3nav.api.newauth import auth_responses
from c3nav.mapdata.models import Level, Source
from c3nav.mapdata.schemas.filters import LevelFilters
from c3nav.mapdata.schemas.models import LevelSchema
from c3nav.mapdata.schemas.responses import BoundsSchema

map_api_router = APIRouter(tags=["map"])


@map_api_router.get('/bounds/', summary="Get map boundaries",
                    response={200: BoundsSchema, **auth_responses})
def bounds(request):
    return {
        "bounds": Source.max_bounds(),
    }


@map_api_router.get('/levels/', response=list[LevelSchema],
                    summary="List available levels")
@paginate
def levels_list(request, filters: Query[LevelFilters]):
    # todo: access, caching, filtering, etc
    return Level.objects.all()


@map_api_router.get('/levels/{level_id}/', response=LevelSchema,
                    summary="List available levels")
def level_detail(request, level_id: int):
    # todo: access, caching, filtering, etc
    try:
        level = Level.objects.get(id=level_id)
    except Level.DoesNotExist:
        raise API404("level not found")
    return level
