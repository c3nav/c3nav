from typing import Optional
from urllib.parse import urlparse

from django.http import HttpResponse
from ninja import Router as APIRouter
from ninja import Schema
from pydantic import PositiveInt

from c3nav.api.newauth import auth_responses
from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.models import MapUpdate
from c3nav.mapdata.newapi.base import newapi_etag
from c3nav.mapdata.schemas.responses import BoundsSchema
from c3nav.mapdata.utils.cache.stats import increment_cache_key
from c3nav.mapdata.utils.user import get_user_data
from c3nav.mapdata.views import set_tile_access_cookie

updates_api_router = APIRouter(tags=["updates"])


class UserDataSchema(Schema):
    logged_in: bool
    allow_editor: bool
    allow_control_panel: bool
    has_positions: bool
    title: NonEmptyStr
    subtitle: NonEmptyStr
    permissions: list[PositiveInt]


class FetchUpdatesResponseSchema(Schema):
    last_site_update: PositiveInt
    last_map_update: NonEmptyStr
    user: Optional[UserDataSchema] = None


@updates_api_router.get('/fetch/', summary="fetch updates",
                        description="get regular updates.\n\n"
                                    "this endpoint also sets/updates the tile access cookie."
                                    "if not called regularly, the tileserver will ignore your access permissions.\n\n"
                                    "this endpoint can be called cross-origin, but it will have no user data then.",
                        response={200: FetchUpdatesResponseSchema, **auth_responses})
def fetch_updates(request, response: HttpResponse):
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
