from enum import StrEnum
from typing import Annotated, Any, Optional, Union

from django.core.exceptions import ValidationError
from django.conf import settings
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from ninja import Field as APIField
from ninja import Router as APIRouter
from ninja import Schema
from pydantic import PositiveInt

from c3nav.api.auth import APIKeyAuth, auth_responses, validate_responses
from c3nav.api.exceptions import APIRequestValidationFailed
from c3nav.api.schema import BaseSchema
from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.api.base import api_stats_clean_location_value
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.models.locations import Position
from c3nav.mapdata.schemas.model_base import AnyLocationID, Coordinates3D
from c3nav.mapdata.utils.cache.stats import increment_cache_key
from c3nav.mapdata.utils.locations import visible_locations_for_request
from c3nav.routing.exceptions import LocationUnreachable, NoRouteFound, NotYetRoutable
from c3nav.routing.forms import RouteForm
from c3nav.routing.models import RouteOptions
from c3nav.routing.router import Router

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


class RestrictedAreas(StrEnum):
    """ whether to prefer or avoid restricted areas """
    NORMAL = "normal"
    PREFER = "prefer"
    AVOID = "avoid"


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


class UpdateRouteOptionsSchema(BaseSchema):
    # todo: default is wrong, this should be optional
    mode: Union[
        Annotated[RouteMode, APIField(title="route mode", description="routing mode to use")],
        Annotated[None, APIField(title="null", description="don't change routing mode")],
    ] = APIField(
        default=None,
        title="routing mode",
    )
    walk_speed: Union[
        Annotated[WalkSpeed, APIField(title="walk speed", description="walk speed to use")],
        Annotated[None, APIField(title="null", description="don't change walk speed")],
    ] = APIField(
        default=None,
        title="walk speed",
    )
    restrictions: Union[
        Annotated[RestrictedAreas, APIField(title="restricted areas",
                                            description="whether to route through restricted areas")],
        Annotated[None, APIField(title="null", description="don't change restricted areas routing")],
    ]
    way_types: dict[
        Annotated[NonEmptyStr, APIField(title="waytype")],
        Union[
            Annotated[LevelWayTypeChoice, APIField(title="waytype without altitude change")],
            Annotated[AltitudeWayTypeChoice, APIField(title="waytype with altitude change")],
        ]
    ] = APIField(
        default_factory=dict,
        title="waytype settings",
    )


class RouteOptionsSchema(BaseSchema):
    # todo: default is wrong, this should be optional
    mode: RouteMode = APIField(name="routing mode")
    walk_speed: WalkSpeed = APIField(name="walk speed")
    restrictions: RestrictedAreas = APIField(title="restricted areas")
    way_types: dict[
        Annotated[NonEmptyStr, APIField(title="waytype")],
        Union[
            Annotated[LevelWayTypeChoice, APIField(title="waytype without altitude change")],
            Annotated[AltitudeWayTypeChoice, APIField(title="waytype with altitude change")],
        ]
    ] = APIField(
        title="waytype settings",
    )


class RouteParametersSchema(BaseSchema):
    origin: AnyLocationID
    destination: AnyLocationID
    options_override: Optional[UpdateRouteOptionsSchema] = APIField(
        None,
        title="override routing options",
    )


class RouteItemSchema(BaseSchema):
    id: PositiveInt
    coordinates: Coordinates3D
    waytype: Union[
        Annotated[dict, APIField(title="waytype", descripiton="waytype used for this segment")],
        Annotated[None, APIField(title="null", description="no waytype (normal walking)")],
    ] = APIField(None, title="waytype")
    space: Union[
        Annotated[dict, APIField(title="space", descripiton="new space that is being entered")],
        Annotated[None, APIField(title="null", description="staying in the same space")],
    ] = APIField(None, description="new space being entered")
    level: Union[
        Annotated[dict, APIField(title="level", descripiton="new level that is being entered")],
        Annotated[None, APIField(title="null", description="staying in the same level")],
    ] = APIField(None, description="new level being entered")
    descriptions: list[tuple[
        Annotated[NonEmptyStr, APIField(
            title="icon name",
            description="any material design icon name"
        )],
        Annotated[NonEmptyStr, APIField(
            title="instruction",
            description="navigation instruction"
        )]
    ]]


class RouteSchema(BaseSchema):
    origin: dict  # todo: improve this
    destination: dict  # todo: improve this
    distance: float
    duration: int
    distance_str: NonEmptyStr
    duration_str: NonEmptyStr
    summary: NonEmptyStr
    options_summary: NonEmptyStr
    items: list[RouteItemSchema]


class RouteResponse(BaseSchema):
    request: RouteParametersSchema
    options: RouteOptionsSchema
    options_form: Any
    report_issue_url: NonEmptyStr
    result: RouteSchema

    class Config(Schema.Config):
        title = "route found"


class NoRouteResponse(BaseSchema):
    request: RouteParametersSchema
    options: RouteOptionsSchema
    error: NonEmptyStr = APIField(
        name="error description",
        description=("the routing parameters were valid, but it was not possible to determine a route. "
                     "this field contains the reason.")
    )

    class Config(Schema.Config):
        title = "route could not be determined"


def get_request_pk(location):
    return location.slug if isinstance(location, Position) else location.pk


@routing_api_router.post('/route/', summary="query route", auth=APIKeyAuth(is_readonly=True),
                         description="query route between two locations",
                         response={200: RouteResponse | NoRouteResponse, **validate_responses, **auth_responses})
# todo: route failure responses
def get_route(request, parameters: RouteParametersSchema):
    form = RouteForm({
        "origin": parameters.origin,
        "destination": parameters.destination,
    }, request=request)

    if not form.is_valid():
        return APIRequestValidationFailed("\n".join(form.errors))

    options = RouteOptions.get_for_request(request)
    if parameters.options_override is not None:
        _new_update_route_options(options, parameters.options_override)

    try:
        route = Router.load().get_route(origin=form.cleaned_data['origin'],
                                        destination=form.cleaned_data['destination'],
                                        permissions=AccessPermission.get_for_request(request),
                                        options=options)
    except NotYetRoutable:
        return NoRouteResponse(
            request=parameters,
            options=_new_serialize_route_options(options),
            error=_('Not yet routable, try again shortly.'),
        )
    except LocationUnreachable:
        return NoRouteResponse(
            request=parameters,
            options=_new_serialize_route_options(options),
            error=_('Unreachable location.')
        )
    except NoRouteFound:
        return NoRouteResponse(
            request=parameters,
            options=_new_serialize_route_options(options),
            error=_('No route found.')
        )

    origin_values = api_stats_clean_location_value(form.cleaned_data['origin'].pk)
    destination_values = api_stats_clean_location_value(form.cleaned_data['destination'].pk)
    increment_cache_key('apistats__route')
    for origin_value in origin_values:
        for destination_value in destination_values:
            increment_cache_key('apistats__route_tuple_%s_%s' % (origin_value, destination_value))
    for value in origin_values:
        increment_cache_key('apistats__route_origin_%s' % value)
    for value in destination_values:
        increment_cache_key('apistats__route_destination_%s' % value)

    return RouteResponse(
        request=parameters,
        options=_new_serialize_route_options(options),
        options_form=options.serialize(),
        report_issue_url=reverse('site.report_start', kwargs={
            'origin': parameters.origin,
            'destination': parameters.destination,
            'options': options.serialize_string(),
        }),
        result=route.serialize(locations=visible_locations_for_request(request)),
    )


if settings.METRICS:
    from c3nav.mapdata.metrics import APIStatsCollector
    APIStatsCollector.add_stat('route')
    APIStatsCollector.add_stat('route_tuple', ['origin', 'destination'])
    APIStatsCollector.add_stat('route_origin', ['origin'])
    APIStatsCollector.add_stat('route_destination', ['destination'])


def _new_serialize_route_options(options):
    # todo: RouteOptions should obviously be modernized
    main_options = {}
    waytype_options = {}
    for key, value in options.items():
        if key.startswith("waytype_"):
            waytype_options[key.removeprefix("waytype_")] = value
        else:
            main_options[key] = value
    return {
        **main_options,
        "way_types": waytype_options,
    }


def _new_update_route_options(options, new_options):
    convert_options = new_options.dict()
    waytype_options = convert_options.pop("way_types", {})
    convert_options.update({f"waytype_{key}": value for key, value in waytype_options.items()})

    try:
        options.update(convert_options, ignore_unknown=True)
    except ValidationError as e:
        raise APIRequestValidationFailed(str(e))


@routing_api_router.get('/options/', summary="current route options",
                        description="get current preferred route options for this user (or session, if signed out)",
                        response={200: RouteOptionsSchema, **auth_responses})
def get_route_options(request):
    # todo: API key should not override for user
    options = RouteOptions.get_for_request(request)
    return _new_serialize_route_options(options)


@routing_api_router.put('/options/', summary="set route options",
                        description="set current preferred route options for this user (or session, if signed out)",
                        response={200: RouteOptionsSchema, **validate_responses, **auth_responses})
def set_route_options(request, new_options: UpdateRouteOptionsSchema):
    options = RouteOptions.get_for_request(request)

    _new_update_route_options(options, new_options)
    options.save()

    return _new_serialize_route_options(options)


class RouteOptionsFieldChoices(BaseSchema):
    name: NonEmptyStr
    title: NonEmptyStr


class RouteOptionsField(BaseSchema):
    name: NonEmptyStr
    type: NonEmptyStr
    label: NonEmptyStr
    choices: list[RouteOptionsFieldChoices]
    value: NonEmptyStr
    value_display: NonEmptyStr


@routing_api_router.get('/options/form/', summary="get route options form",
                        description="get description of all form options, to render like a form (like old API)",
                        response={200: list[RouteOptionsField], **auth_responses})
def get_route_options_form(request):
    options = RouteOptions.get_for_request(request)
    data = options.serialize()
    for option in data:
        if option["name"].startswith("waytype_"):
            option["name"] = "way_types."+data["name"].removeprefix("waytype_")
    return data
