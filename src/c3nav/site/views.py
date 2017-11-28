# flake8: noqa
import json
from collections import OrderedDict
from typing import Optional

import qrcode
from django.conf import settings
from django.core.cache import cache
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.urls import reverse

from c3nav.mapdata.models import Location, Source
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.models.level import Level
from c3nav.mapdata.models.locations import LocationRedirect, SpecificLocation
from c3nav.mapdata.utils.locations import get_location_by_slug_for_request, levels_by_short_label_for_request
from c3nav.mapdata.views import set_tile_access_cookie

ctype_mapping = {
    'yes': ('up', 'down'),
    'up': ('up', ),
    'down': ('down', ),
    'no': ()
}


def get_ctypes(prefix, value):
    return tuple((prefix+'_'+direction) for direction in ctype_mapping.get(value, ('up', 'down')))


def reverse_ctypes(ctypes, name):
    if name+'_up' in ctypes:
        return 'yes' if name + '_down' in ctypes else 'up'
    else:
        return 'down' if name + '_down' in ctypes else 'no'


def get_location_or_404(request, location):
    if location is None:
        return None

    get_location = None
    location = get_location(request, location)
    if location is None:
        raise Http404

    return location


def qr_code(request, location):
    location = get_location_or_404(request, location)

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(request.build_absolute_uri(reverse('site.location', kwargs={'location': location.location_id})))
    qr.make(fit=True)

    response = HttpResponse(content_type='image/png')
    qr.make_image().save(response, 'PNG')
    return response


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


@set_tile_access_cookie
def map_index(request, mode=None, slug=None, slug2=None, details=None, level=None, x=None, y=None, zoom=None):
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
            'level': level[0],
            'center': (float(x), float(y)),
            'zoom': float(zoom),
        })

    ctx = {
        'bounds': json.dumps(Source.max_bounds(), separators=(',', ':')),
        'levels': json.dumps(tuple(levels.values()), separators=(',', ':')),
        'state': json.dumps(state, separators=(',', ':')),
        'tile_cache_server': settings.TILE_CACHE_SERVER,
    }
    return render(request, 'site/map.html', ctx)
