import json
from typing import Optional

import qrcode
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.cache import cache_control
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import etag

from c3nav.mapdata.models import Location, Source
from c3nav.mapdata.models.locations import LocationRedirect, SpecificLocation
from c3nav.mapdata.utils.locations import get_location_by_slug_for_request, levels_by_short_label_for_request
from c3nav.mapdata.utils.user import get_user_data
from c3nav.mapdata.views import set_tile_access_cookie


def check_location(location: Optional[str], request) -> Optional[SpecificLocation]:
    if location is None:
        return None

    location = get_location_by_slug_for_request(location, request)
    if location is None:
        return None

    if isinstance(location, LocationRedirect):
        location: Location = location.target
    if location is None:
        return None

    if not location.can_search:
        location = None

    return location


def map_index(request, mode=None, slug=None, slug2=None, details=None,
              level=None, x=None, y=None, zoom=None, embed=None):
    origin = None
    destination = None
    routing = False
    if slug2 is not None:
        routing = True
        origin = check_location(slug, request)
        destination = check_location(slug2, request)
    else:
        routing = (mode and mode != 'l')
        if mode == 'o':
            origin = check_location(slug, request)
        else:
            destination = check_location(slug, request)

    state = {
        'routing': routing,
        'origin': (origin.serialize(detailed=False, simple_geometry=True, geometry=False)
                   if origin else None),
        'destination': (destination.serialize(detailed=False, simple_geometry=True, geometry=False)
                        if destination else None),
        'sidebar': routing or destination is not None,
        'details': True if details else False,
    }

    levels = levels_by_short_label_for_request(request)

    level = levels.get(level, None) if level else None
    if level is not None:
        state.update({
            'level': level.pk,
            'center': (float(x), float(y)),
            'zoom': float(zoom),
        })

    ctx = {
        'bounds': json.dumps(Source.max_bounds(), separators=(',', ':')),
        'levels': json.dumps(tuple((level.pk, level.short_label) for level in levels.values()), separators=(',', ':')),
        'state': json.dumps(state, separators=(',', ':'), cls=DjangoJSONEncoder),
        'tile_cache_server': settings.TILE_CACHE_SERVER,
        'user_data': get_user_data(request),
        'embed': bool(embed),
    }
    response = render(request, 'site/map.html', ctx)
    set_tile_access_cookie(request, response)
    if embed:
        xframe_options_exempt(lambda: response)()
    return response


def qr_code_etag(request, path):
    return '1'


@etag(qr_code_etag)
@cache_control(max_age=3600)
def qr_code(request, path):
    data = (request.build_absolute_uri('/'+path) +
            ('?'+request.META['QUERY_STRING'] if request.META['QUERY_STRING'] else ''))
    if len(data) > 256:
        return HttpResponseBadRequest()

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)

    response = HttpResponse(content_type='image/png')
    qr.make_image().save(response, 'PNG')
    return response
