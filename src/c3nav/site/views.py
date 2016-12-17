import os

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from PIL import Image, ImageDraw

from c3nav.mapdata.models import Level
from c3nav.mapdata.models.locations import get_location
from c3nav.mapdata.render.compose import composer
from c3nav.mapdata.utils.misc import get_dimensions
from c3nav.routing.graph import Graph
from c3nav.routing.utils.draw import _line_coords


def main(request, origin=None, destination=None):
    do_redirect = False

    if origin:
        origin_obj = get_location(request, origin)
        if origin_obj.name != origin:
            do_redirect = True
        origin = origin_obj

    if destination:
        destination_obj = get_location(request, destination)
        if destination_obj.name != destination:
            do_redirect = True
        destination = destination_obj

    if do_redirect:
        new_url = '/'
        if origin:
            new_url += origin.name+'/'
            if destination:
                new_url += destination.name + '/'
        elif destination:
            new_url += '_/' + destination.name + '/'

        redirect(new_url)

    route = None
    if origin and destination:
        graph = Graph.load()
        route = graph.get_route(origin, destination, ('', 'steps_down', 'steps_up', 'elevator_down', 'elevator_up'))
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
