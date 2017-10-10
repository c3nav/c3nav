import subprocess

from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from shapely.geometry import box

from c3nav.mapdata.models import Level, Source
from c3nav.mapdata.render import render_svg


def tile(request, level, zoom, x, y, format):
    zoom = int(zoom)
    if not (0 <= zoom <= 10):
        raise Http404

    bounds = Source.max_bounds()

    x, y = int(x), int(y)
    size = 256/2**zoom
    minx = size * x
    miny = size * y
    maxx = minx + size
    maxy = miny + size

    if not box(bounds[0][1], bounds[0][0], bounds[1][1], bounds[1][0]).intersects(box(minx, miny, maxx, maxy)):
        raise Http404

    level = get_object_or_404(Level, pk=level)

    svg = render_svg(level, miny, minx, maxy, maxx, scale=2**zoom)

    if format == 'svg':
        response = HttpResponse(svg, 'image/svg+xml')
    elif format == 'png':
        p = subprocess.run(('rsvg-convert', '--format', 'png'), input=svg.encode(), stdout=subprocess.PIPE, check=True)
        response = HttpResponse(p.stdout, content_type="image/png")
    else:
        raise ValueError

    return response
