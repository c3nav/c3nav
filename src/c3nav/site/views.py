import os

from django.conf import settings
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from PIL import Image, ImageDraw

from c3nav.mapdata.models import Level
from c3nav.mapdata.models.locations import get_location
from c3nav.mapdata.render.compose import composer
from c3nav.mapdata.utils.misc import get_dimensions
from c3nav.routing.graph import Graph
from c3nav.routing.utils.draw import _line_coords

ctype_mapping = {
    'yes': ('up', 'down'),
    'up': ('up', ),
    'down': ('down', ),
    'no': ()
}


def get_ctypes(prefix, value):
    return tuple((prefix+'_'+direction) for direction in ctype_mapping.get(value, ('up', 'dowm')))


def main(request, origin=None, destination=None):
    if origin:
        origin = get_location(request, origin)
        if origin is None:
            raise Http404

    if destination:
        destination = get_location(request, destination)
        if destination is None:
            raise Http404

    route = None
    if request.method == 'POST' and origin and destination:
        graph = Graph.load()

        allowed_ctypes = ('', )
        allowed_ctypes += get_ctypes('stairs', request.POST.get('stairs'))
        allowed_ctypes += get_ctypes('escalator', request.POST.get('escalators'))
        allowed_ctypes += get_ctypes('elevator', request.POST.get('elevators'))

        route = graph.get_route(origin, destination, allowed_ctypes)
        print(route)
        route = route.split()
        print(route)

        if False:
            filename = os.path.join(settings.RENDER_ROOT, 'base-level-0.png')

            im = Image.open(filename)
            height = im.size[1]
            draw = ImageDraw.Draw(im)
            for connection in route.connections:
                draw.line(_line_coords(connection.from_point, connection.to_point, height), fill=(255, 100, 100))

            response = HttpResponse(content_type="image/png")
            im.save(response, "PNG")
            return response

    width, height = get_dimensions()

    return render(request, 'site/main.html', {
        'origin': origin,
        'destination': destination,
        'route': route,
        'width': width,
        'height': height,
        'svg_width': width*6,
        'svg_height': height*6,
    })


def level_image(request, level):
    level = get_object_or_404(Level, name=level, intermediate=False)
    return composer.get_level_image(request, level)
