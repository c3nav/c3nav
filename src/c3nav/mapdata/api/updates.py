from typing import Annotated, Optional, Union
from urllib.parse import urlparse

from django.http import HttpResponse
from ninja import Field as APIField
from ninja import Router as APIRouter
from ninja import Schema
from pydantic import PositiveInt

from c3nav.api.auth import auth_responses
from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.models import MapUpdate
from c3nav.mapdata.utils.cache.stats import increment_cache_key
from c3nav.mapdata.utils.user import get_user_data
from c3nav.mapdata.views import set_tile_access_cookie

updates_api_router = APIRouter(tags=["updates"])


class UserDataSchema(Schema):
    logged_in: bool = APIField(
        title="logged in",
        description="whether a user is logged in",
    )
    allow_editor: bool = APIField(
        title="editor access",
        description="whether the user signed in can access the editor (or accessing the editor is possible as guest)."
                    "this does not mean that the current API authorization allows accessing the editor API.",
    )
    allow_control_panel: bool = APIField(
        title="control panel access",
        description="whether the user signed in can access the control panel.",
    )
    has_positions: bool = APIField(
        title="user has positions",
        description="whether the user signed in has created any positions",
    )
    title: NonEmptyStr = APIField(
        title="user data title",
        description="data to show in the top right corner. can be the user name or `Login` or similar",
        example="ada_lovelace",
    )
    subtitle: NonEmptyStr = APIField(
        title="user data subtitle",
        description="a description of the current user data state to display below the user data title",
        example="3 areas unlocked",
    )
    permissions: list[PositiveInt] = APIField(
        title="access permissions",
        description="IDs of access restrictions that this user (even if maybe not signed in) has access to",
        example=[2, 5],
    )


class FetchUpdatesResponseSchema(Schema):
    last_site_update: PositiveInt = APIField(
        title="ID of the last site update",
        description="If this ID changes, it means a major code change may have occured. "
                    "A reload of all data is recommended.",
        example=1,
    )
    last_map_update: NonEmptyStr = APIField(
        title="string identifier of the last map update",
        description="Map updates are incremental, not every map update will change all data. API endpoitns will be "
                    "aware of this. Use `E-Tag` and `If-None-Match` on API endpoints to query if the data has changed.",
    )
    user_data: Union[
        Annotated[UserDataSchema, APIField(
            title="user data",
            description="always supplied, unless it is a cross-origin request",
        )],
        Annotated[None, APIField(
            title="null",
            description="only for cross-origin requests",
        )],
    ] = APIField(
        None,
        title="user data",
        description="user data of this request. ommited for cross-origin requests.",
    )


@updates_api_router.get('/fetch/', summary="fetch updates",
                        response={200: FetchUpdatesResponseSchema, **auth_responses})
def fetch_updates(request, response: HttpResponse):
    """
    Get regular updates.

    This endpoint also sets/updates the tile access cookie.
    If not called regularly, the tileserver will ignore your access permissions.

    This endpoint can be called cross-origin, but it will have no user data then.
    """
    cross_origin = request.META.get('HTTP_ORIGIN')
    if cross_origin is not None:
        try:
            if request.META['HTTP_HOST'] == urlparse(cross_origin).hostname:
                cross_origin = None
        except ValueError:
            pass

    increment_cache_key('api_updates_fetch_requests%s' % ('_cross_origin' if cross_origin is not None else ''))

    from c3nav.site.models import SiteUpdate

    result = {
        'last_site_update': SiteUpdate.last_update(),
        'last_map_update': MapUpdate.current_processed_cache_key(),
    }
    if cross_origin is None:
        result.update({
            'user': get_user_data(request),
        })

    if cross_origin is not None:
        response['Access-Control-Allow-Origin'] = cross_origin
        response['Access-Control-Allow-Credentials'] = 'true'
    set_tile_access_cookie(request, response)

    return result
