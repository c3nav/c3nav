from enum import StrEnum
from typing import Annotated, Union, Optional

from ninja import Router as APIRouter, Schema, Field as APIField

from c3nav.api.newauth import auth_responses, validate_responses
from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.models import Source
from pydantic import PositiveInt
from c3nav.mapdata.schemas.model_base import AnyLocationID, Coordinates3D
from c3nav.mapdata.schemas.responses import BoundsSchema

routing_api_router = APIRouter(tags=["routing"])


class RouteMode(StrEnum):
    """ how to optimize the route """
    FASTEST = "fastest"
    SHORTEST = "shortest"


class WalkSpeed(StrEnum):
    """ the walk speed """
    SLOW = "slow"
    DEFAULT = "default"
    FAST = "fast"


class LevelWayTypeChoice(StrEnum):
    """ route preferences for way types that are level """
    ALLOW = "allow"
    AVOID = "avoid"


class AltitudeWayTypeChoice(StrEnum):
    """ route preferences for way types that overcome a change in altitude """
    ALLOW = "allow"
    AVOID_UP = "avoid_up"
    AVOID_DOWN = "avoid_down"
    AVOID = "avoid"


class RouteOptionsSchema(Schema):
    mode: RouteMode = RouteMode.FASTEST
    walk_speed: WalkSpeed = WalkSpeed.DEFAULT
    way_types: dict[
        Annotated[NonEmptyStr, APIField(title="waytype")],
        Union[
            Annotated[LevelWayTypeChoice, APIField(default=LevelWayTypeChoice.ALLOW)],
            Annotated[AltitudeWayTypeChoice, APIField(default=AltitudeWayTypeChoice.ALLOW)],
        ]
    ] = APIField(default_factory=dict)


class RouteParametersSchema(Schema):
    origin: AnyLocationID
    destination: AnyLocationID
    options_override: Optional[RouteOptionsSchema] = None


class RouteItemSchema(Schema):
    id: PositiveInt
    coordinates: Coordinates3D
    way_type: Optional[dict]  # todo: improve
    space: Optional[dict] = APIField(title="new space being entered")
    level: Optional[dict] = APIField(title="new level being entered")
    descriptions: list[NonEmptyStr]


class RouteSchema(Schema):
    origin: dict  # todo: improve this
    destination: dict  # todo: improve this
    distance: float
    duration: int
    distance_str: NonEmptyStr
    duration_str: NonEmptyStr
    summary: NonEmptyStr
    options_summary: NonEmptyStr
    items: list[RouteItemSchema]


@routing_api_router.post('/route/', summary="get route between two locations",
                         response={200: RouteSchema, **validate_responses, **auth_responses})
# todo: route failure responses
def get_route(request, parameters: RouteParametersSchema):
    # todo: implement
    raise NotImplementedError


@routing_api_router.get('/options/', summary="get current route options",
                        response={200: RouteOptionsSchema, **auth_responses})
def get_route_options(request):
    # todo: implement
    raise NotImplementedError


@routing_api_router.put('/options/', summary="set route options for user or session",
                        response={200: RouteOptionsSchema, **validate_responses, **auth_responses})
def set_route_options(request, options: RouteOptionsSchema):
    # todo: implement
    raise NotImplementedError


class RouteOptionsFieldChoices(Schema):
    name: NonEmptyStr
    title: NonEmptyStr


class RouteOptionsField(Schema):
    name: NonEmptyStr
    type: NonEmptyStr
    label: NonEmptyStr
    choices: list[RouteOptionsFieldChoices]
    value: NonEmptyStr
    value_display: NonEmptyStr


@routing_api_router.get('/options/form/', summary="get current route options with form definitions (like old API)",
                        response={200: list[RouteOptionsField], **auth_responses})
def get_route_options_form(request):
    # todo: implement
    raise NotImplementedError
