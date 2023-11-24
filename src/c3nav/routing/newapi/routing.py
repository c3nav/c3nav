from ninja import Router as APIRouter

from c3nav.api.newauth import auth_responses
from c3nav.mapdata.models import Source
from c3nav.mapdata.schemas.responses import BoundsSchema

routing_api_router = APIRouter(tags=["routing"])


@routing_api_router.post('/route/', summary="get route between two locations",
                         response={200: BoundsSchema, **auth_responses})
def get_route(request):
    # todo: implement
    return {
        "bounds": Source.max_bounds(),
    }

@routing_api_router.get('/options/', summary="get current route options",
                         response={200: BoundsSchema, **auth_responses})
def get_route_options(request):
    # todo: implement
    return {
        "bounds": Source.max_bounds(),
    }


@routing_api_router.put('/options/', summary="set route options for user or session",
                        response={200: BoundsSchema, **auth_responses})
def set_route_options(request):
    # todo: implement
    return {
        "bounds": Source.max_bounds(),
    }


@routing_api_router.get('/options/form/', summary="get current route options with form definitions (like old API)",
                         response={200: BoundsSchema, **auth_responses})
def get_route_options_form(request):
    # todo: implement
    return {
        "bounds": Source.max_bounds(),
    }
