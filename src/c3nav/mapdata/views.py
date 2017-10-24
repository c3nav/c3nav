import os

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, HttpResponseNotModified
from django.shortcuts import get_object_or_404
from shapely.geometry import box

from c3nav.mapdata.cache import MapHistory
from c3nav.mapdata.models import Level, MapUpdate, Source
from c3nav.mapdata.render.base import get_render_level_ids
from c3nav.mapdata.render.svg import SVGRenderer


def tile(request, level, zoom, x, y, format):
    zoom = int(zoom)
    if not (0 <= zoom <= 10):
        raise Http404

    # calculate bounds
    x, y = int(x), int(y)
    size = 256/2**zoom
    minx = size * x
    miny = size * (-y-1)
    maxx = minx + size
    maxy = miny + size

    # error 404 if tiles is out of bounds
    bounds = Source.max_bounds()
    if not box(bounds[0][1], bounds[0][0], bounds[1][1], bounds[1][0]).intersects(box(minx, miny, maxx, maxy)):
        raise Http404

    # is this a valid level?
    cache_key = MapUpdate.current_cache_key()
    level = int(level)
    if level not in get_render_level_ids(cache_key):
        raise Http404

    # init renderer
    renderer = SVGRenderer(level, miny, minx, maxy, maxx, scale=2**zoom, user=request.user)
    tile_cache_key = renderer.cache_key
    update_cache_key = renderer.update_cache_key

    # check browser cache
    etag = tile_cache_key
    if_none_match = request.META.get('HTTP_IF_NONE_MATCH')
    if if_none_match == etag:
        return HttpResponseNotModified()

    data = None
    tile_dirname, last_update_filename, tile_filename, tile_cache_update_cache_key = '', '', '', ''

    # get tile cache last update
    if settings.CACHE_TILES:
        tile_dirname = os.path.sep.join((settings.TILES_ROOT, str(level), str(zoom), str(x), str(y)))
        last_update_filename = os.path.join(tile_dirname, 'last_update')
        tile_filename = os.path.join(tile_dirname, renderer.access_cache_key+'.'+format)

        # get tile cache last update
        tile_cache_update_cache_key = 'mapdata:tile-cache-update:%d-%d-%d-%d' % (level, zoom, x, y)
        tile_cache_update = cache.get(tile_cache_update_cache_key, None)
        if tile_cache_update is None:
            try:
                with open(last_update_filename) as f:
                    tile_cache_update = f.read()
            except FileNotFoundError:
                pass

        if tile_cache_update != update_cache_key:
            os.system('rm -rf '+os.path.join(tile_dirname, '*'))
        else:
            try:
                with open(tile_filename, 'rb') as f:
                    data = f.read()
            except FileNotFoundError:
                pass

    content_type = 'image/svg+xml' if format == 'svg' else 'image/png'

    if data is None:
        svg = renderer.render()
        if format == 'svg':
            data = svg.get_xml()
            filemode = 'w'
        elif format == 'png':
            data = svg.get_png()
            filemode = 'wb'
        else:
            raise ValueError

        if settings.CACHE_TILES:
            os.makedirs(tile_dirname, exist_ok=True)
            with open(tile_filename, filemode) as f:
                f.write(data)
            with open(last_update_filename, 'w') as f:
                f.write(update_cache_key)
            cache.get(tile_cache_update_cache_key, update_cache_key, 60)

    response = HttpResponse(data, content_type)
    response['ETag'] = etag
    response['Cache-Control'] = 'no-cache'

    return response


def history(request, level, mode, format):
    if not request.user.is_superuser:
        raise PermissionDenied
    level = get_object_or_404(Level, pk=level)

    if mode == 'render' and level.on_top_of_id is not None:
        raise Http404

    history = MapHistory.open_level(level.pk, mode)
    if format == 'png':
        response = HttpResponse(content_type='image/png')
        history.to_image().save(response, format='PNG')
    elif format == 'data':
        response = HttpResponse(content_type='application/octet-stream')
        history.write(response)
    else:
        raise ValueError
    return response
