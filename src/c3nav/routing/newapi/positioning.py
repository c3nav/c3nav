from ninja import Router as APIRouter

from c3nav.api.newauth import auth_responses
from c3nav.mapdata.models import Source
from c3nav.mapdata.schemas.responses import BoundsSchema

positioning_api_router = APIRouter(tags=["positioning"])


@positioning_api_router.post('/locate/', summary="locate based on wifi scans",
                             response={200: BoundsSchema, **auth_responses})
def locate(request):
    # todo: implement
    return {
        "bounds": Source.max_bounds(),
    }

@positioning_api_router.get('/locate-test/', summary="get dummy location for debugging",
                            response={200: BoundsSchema, **auth_responses})
def locate_test(request):
    # todo: implement
    return {
        "bounds": Source.max_bounds(),
    }
