from datetime import timedelta

from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone

from c3nav.mapdata.models import Level
from c3nav.mapdata.models.locations import get_location, search_location
from c3nav.mapdata.permissions import get_excludables_includables
from c3nav.mapdata.render.compose import composer
from c3nav.mapdata.utils.misc import get_dimensions
from c3nav.routing.graph import Graph

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

    location = get_location(request, location)
    if location is None:
        raise Http404

    return location


def main(request, location=None, origin=None, destination=None):
    location = get_location_or_404(request, location)
    origin = get_location_or_404(request, origin)
    destination = get_location_or_404(request, destination)

    mode = 'location' if not origin and not destination else 'route'

    ctx = {
        'location': location,
        'origin': origin,
        'destination': destination,
        'mode': mode,
    }

    search = None
    if not origin and not destination:
        search = 'location'
    elif origin and not destination:
        search = 'destination'
    elif destination and not origin:
        search = 'origin'

    if search is not None:
        search_query = request.POST.get(search+'_search', '').strip() or None
        if search_query:
            results = search_location(request, search_query)

            url = 'site.location' if search == 'location' else 'site.route'
            kwargs = {}
            if origin:
                kwargs['origin'] = origin.location_id
            if destination:
                kwargs['destination'] = destination.location_id
            for result in results:
                kwargs[search] = result.location_id
                result.url = reverse(url, kwargs=kwargs)

            ctx.update({
                'search': search,
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

    excludables, includables = get_excludables_includables()
    include = set(include) & set(includables)
    avoid = set(avoid) & set(excludables)

    if request.method == 'POST':
        save_settings = request.POST.get('save_settings', '') == '1'

    ctx.update({
        'stairs': stairs,
        'escalators': escalators,
        'elevators': elevators,
        'excludables': excludables.items(),
        'includables': includables.items(),
        'include': include,
        'avoid': avoid,
        'save_settings': save_settings,
    })

    # routing
    if request.method == 'POST' and origin and destination:
        public = ':public' not in avoid
        nonpublic = ':nonpublic' in include

        graph = Graph.load()
        route = graph.get_route(origin, destination, allowed_ctypes, public=public, nonpublic=nonpublic,
                                avoid=avoid-set(':public'), include=include-set(':nonpublic'))
        route = route.split()
        route.create_routeparts()

        ctx.update({
            'route': route,
        })

    width, height = get_dimensions()

    ctx.update({
        'width': width,
        'height': height,
        'svg_width': width*6,
        'svg_height': height*6,
    })

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


def level_image(request, level):
    level = get_object_or_404(Level, name=level, intermediate=False)
    return composer.get_level_image(request, level)
