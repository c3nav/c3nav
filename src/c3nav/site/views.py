# flake8: noqa
from datetime import timedelta

import qrcode
from django.core.files import File
from django.http import Http404, HttpResponse, HttpResponseNotModified, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from c3nav.mapdata.models.level import Level

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


def main(request, location=None, origin=None, destination=None):
    location = get_location_or_404(request, location)
    origin = get_location_or_404(request, origin)
    destination = get_location_or_404(request, destination)

    mode = 'location' if not origin and not destination else 'route'

    active_field = None
    if not origin and not destination:
        active_field = 'location'
    elif origin and not destination:
        active_field = 'destination'
    elif destination and not origin:
        active_field = 'origin'

    ctx = {
        'location': location,
        'origin': origin,
        'destination': destination,
        'mode': mode,
        'active_field': active_field,

        'full_access': request.c3nav_full_access,
        'access_list': request.c3nav_access_list,
        'visible_areas': get_visible_areas(request),
    }

    width, height = get_dimensions()
    sections = tuple(section for id_, section in get_sections_cached().items())

    ctx.update({
        'width': width,
        'height': height,
        'svg_width': int(width * 6),
        'svg_height': int(height * 6),
        'sections': sections,
    })

    map_level = request.GET.get('map-level')
    if map_level in sections:
        ctx.update({
            'map_level': map_level
        })

        if 'x' in request.POST and 'y' in request.POST:
            x = request.POST.get('x')
            y = request.POST.get('y')
            if x.isnumeric() and y.isnumeric():
                coords = 'c:%s:%d:%d' % (map_level, int(int(x)/6*100), height-int(int(y)/6*100))
                if active_field == 'origin':
                    return redirect('site.route', origin=coords, destination=destination.location_id)
                elif active_field == 'destination':
                    return redirect('site.route', origin=origin.location_id, destination=coords)
                elif active_field == 'location':
                    return redirect('site.location', location=coords)

    if active_field is not None:
        search_query = request.POST.get(active_field+'_search', '').strip() or None
        if search_query:
            results = search_location(request, search_query)

            url = 'site.location' if active_field == 'location' else 'site.route'
            kwargs = {}
            if origin:
                kwargs['origin'] = origin.location_id
            if destination:
                kwargs['destination'] = destination.location_id
            for result in results:
                kwargs[active_field] = result.location_id
                result.url = reverse(url, kwargs=kwargs)

            ctx.update({
                'search': active_field,
                'search_query': search_query,
                'search_results': results,
            })

    # everything about settings
    include = ()
    avoid = ()
    stairs = 'yes'
    escalators = 'yes'
    elevators = 'yes'

    save_settings = False
    if 'c3nav_settings' in request.COOKIES:
        cookie_value = request.COOKIES['c3nav_settings']

        if isinstance(cookie_value, dict):
            stairs = cookie_value.get('stairs', stairs)
            escalators = cookie_value.get('escalators', escalators)
            elevators = cookie_value.get('elevators', elevators)

            if isinstance(cookie_value.get('include'), list):
                include = cookie_value.get('include')

            if isinstance(cookie_value.get('avoid'), list):
                avoid = cookie_value.get('avoid')

        save_settings = True

    if request.method == 'POST':
        stairs = request.POST.get('stairs', stairs)
        escalators = request.POST.get('escalators', escalators)
        elevators = request.POST.get('elevators', elevators)

        include = request.POST.getlist('include')
        avoid = request.POST.getlist('avoid')

    allowed_ctypes = ('', )
    allowed_ctypes += get_ctypes('stairs', request.POST.get('stairs', stairs))
    allowed_ctypes += get_ctypes('escalator', request.POST.get('escalators', escalators))
    allowed_ctypes += get_ctypes('elevator', request.POST.get('elevators', elevators))

    stairs = reverse_ctypes(allowed_ctypes, 'stairs')
    escalators = reverse_ctypes(allowed_ctypes, 'escalator')
    elevators = reverse_ctypes(allowed_ctypes, 'elevator')

    includables, avoidables = get_includables_avoidables(request)
    allow_nonpublic, include, avoid = parse_include_avoid(request, include, avoid)

    if request.method == 'POST':
        save_settings = request.POST.get('save_settings', '') == '1'

    ctx.update({
        'stairs': stairs,
        'escalators': escalators,
        'elevators': elevators,
        'excludables': avoidables.items(),
        'includables': includables.items(),
        'include': include,
        'avoid': avoid,
        'save_settings': save_settings,
    })

    # routing
    if request.method == 'POST' and origin and destination:
        graph = Graph.load()

        try:
            route = graph.get_route(origin, destination, allowed_ctypes, allow_nonpublic=allow_nonpublic,
                                    avoid=avoid-set(':public'), include=include-set(':nonpublic'))
        except NoRouteFound:
            ctx.update({'error': 'noroutefound'})
        except AlreadyThere:
            ctx.update({'error': 'alreadythere'})
        except NotYetRoutable:
            ctx.update({'error': 'notyetroutable'})
        else:
            route.describe(allowed_ctypes)
            ctx.update({'route': route})

    if request.GET.get('format') == 'json':
        if 'error' in ctx:
            return JsonResponse({'error': ctx['error']})
        if 'route' in ctx:
            return JsonResponse({'route': ctx['route'].serialize()})

    response = render(request, 'site/main.html', ctx)

    if request.method == 'POST' and save_settings:
        cookie_value = {
            'stairs': stairs,
            'escalators': escalators,
            'elevators': elevators,
            'include': tuple(include),
            'avoid': tuple(avoid),
        }
        response.set_cookie('c3nav_settings', cookie_value, expires=timezone.now() + timedelta(days=30))

    return response


def map_image(request, area, level):
    level = get_object_or_404(Level, name=level, intermediate=False)
    if area == ':base':
        img = get_render_path('png', level.name, 'full', True)
    elif area == ':full':
        if not request.c3nav_full_access:
            raise Http404
        img = get_render_path('png', level.name, 'full', False)
    elif area in request.c3nav_access_list:
        img = get_render_path(area+'.png', level.name, 'full', False)
    else:
        raise Http404

    last_update = get_last_mapdata_update()
    etag = '-'.join(str(i) for i in last_update.timetuple())

    if_none_match = request.META.get('HTTP_IF_NONE_MATCH')
    if if_none_match:
        if if_none_match == etag:
            return HttpResponseNotModified()

    response = HttpResponse(content_type='image/png')
    for chunk in File(open(img, 'rb')).chunks():
        response.write(chunk)

    response['ETag'] = etag
    response['Cache-Control'] = 'no-cache'
    return response
