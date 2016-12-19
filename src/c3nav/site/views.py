from datetime import timedelta

from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from c3nav.mapdata.models import Level
from c3nav.mapdata.models.locations import get_location
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


def main(request, origin=None, destination=None):
    if origin:
        origin = get_location(request, origin)
        if origin is None:
            raise Http404

    if destination:
        destination = get_location(request, destination)
        if destination is None:
            raise Http404

    include = ()
    avoid = ()
    stairs = 'yes'
    escalators = 'yes'
    elevators = 'yes'

    save_settings = False
    if 'c3nav_settings' in request.COOKIES:
        cookie_value = request.COOKIES['c3nav_settings']
        print(cookie_value)

        if isinstance(cookie_value, dict):
            stairs = cookie_value.get('stairs', stairs)
            escalators = cookie_value.get('escalators', escalators)
            elevators = cookie_value.get('elevators', elevators)

            if isinstance(cookie_value.get('include'), list):
                include = cookie_value.get('include')

            if isinstance(cookie_value.get('avoid'), list):
                avoid = cookie_value.get('avoid')

        save_settings = True

    if request.method in 'POST':
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

    if request.method in 'POST':
        save_settings = request.POST.get('save_settings', '') == '1'

    route = None
    if request.method in 'POST' and origin and destination:
        public = ':public' not in avoid
        nonpublic = ':nonpublic' in include

        graph = Graph.load()
        route = graph.get_route(origin, destination, allowed_ctypes, public=public, nonpublic=nonpublic,
                                avoid=avoid-set(':public'), include=include-set(':nonpublic'))
        route = route.split()
        route.create_routeparts()

    width, height = get_dimensions()

    response = render(request, 'site/main.html', {
        'origin': origin,
        'destination': destination,

        'stairs': stairs,
        'escalators': escalators,
        'elevators': elevators,
        'excludables': excludables.items(),
        'includables': includables.items(),
        'include': include,
        'avoid': avoid,
        'save_settings': save_settings,

        'route': route,
        'width': width,
        'height': height,
        'svg_width': width*6,
        'svg_height': height*6,
    })

    if request.method in 'POST' and save_settings:
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
