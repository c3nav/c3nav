import base64
import os
from functools import wraps
from wsgiref.util import FileWrapper

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, HttpResponseNotModified, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import etag

from c3nav.mapdata.middleware import no_language
from c3nav.mapdata.models import Level, MapUpdate
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.render.engines import ImageRenderEngine
from c3nav.mapdata.render.renderer import MapRenderer
from c3nav.mapdata.utils.cache import CachePackage, MapHistory
from c3nav.mapdata.utils.tiles import (build_access_cache_key, build_base_cache_key, build_tile_access_cookie,
                                       build_tile_etag, get_tile_bounds, parse_tile_access_cookie)


def set_tile_access_cookie(func):
    @wraps(func)
    def wrapper(request, *args, **kwargs):
        response = func(request, *args, **kwargs)

        access_permissions = AccessPermission.get_for_request(request)
        if access_permissions:
            cookie = build_tile_access_cookie(access_permissions, settings.SECRET_TILE_KEY)
            response.set_cookie(settings.TILE_ACCESS_COOKIE_NAME, cookie, max_age=60,
                                domain=settings.TILE_ACCESS_COOKIE_DOMAIN)
        else:
            response.delete_cookie(settings.TILE_ACCESS_COOKIE_NAME)

        return response
    return wrapper


encoded_tile_secret = base64.b64encode(settings.SECRET_TILE_KEY.encode()).decode()


def enforce_tile_secret_auth(request):
    x_tile_secret = request.META.get('HTTP_X_TILE_SECRET')
    if x_tile_secret:
        if x_tile_secret != encoded_tile_secret:
            raise PermissionDenied
    elif not request.user.is_superuser:
        raise PermissionDenied


@no_language()
def tile(request, level, zoom, x, y, access_permissions=None):
    if access_permissions is not None:
        enforce_tile_secret_auth(request)

    zoom = int(zoom)
    if not (-2 <= zoom <= 5):
        raise Http404

    cache_package = CachePackage.open_cached()

    # check if bounds are valid
    x = int(x)
    y = int(y)
    minx, miny, maxx, maxy = get_tile_bounds(zoom, x, y)
    if not cache_package.bounds_valid(minx, miny, maxx, maxy):
        raise Http404

    # get level
    level = int(level)
    level_data = cache_package.levels.get(level)
    if level_data is None:
        raise Http404

    # decode access permissions
    if access_permissions is None:
        try:
            cookie = request.COOKIES[settings.TILE_ACCESS_COOKIE_NAME]
        except KeyError:
            access_permissions = set()
        else:
            access_permissions = parse_tile_access_cookie(cookie, settings.SECRET_TILE_KEY)
            access_permissions &= set(level_data.restrictions[minx:miny, maxx:maxy])
    else:
        access_permissions = set(int(i) for i in access_permissions.split('-')) - set([0])

    # build cache keys
    last_update = level_data.history.last_update(minx, miny, maxx, maxy)
    base_cache_key = build_base_cache_key(last_update)
    access_cache_key = build_access_cache_key(access_permissions)

    # check browser cache
    tile_etag = build_tile_etag(level, zoom, x, y, base_cache_key, access_cache_key, settings.SECRET_TILE_KEY)
    if_none_match = request.META.get('HTTP_IF_NONE_MATCH')
    if if_none_match == tile_etag:
        return HttpResponseNotModified()

    data = None
    tile_dirname, last_update_filename, tile_filename, tile_cache_update_cache_key = '', '', '', ''

    # get tile cache last update
    if settings.CACHE_TILES:
        tile_dirname = os.path.sep.join((settings.TILES_ROOT, str(level), str(zoom), str(x), str(y)))
        last_update_filename = os.path.join(tile_dirname, 'last_update')
        tile_filename = os.path.join(tile_dirname, access_cache_key+'.png')

        # get tile cache last update
        tile_cache_update_cache_key = 'mapdata:tile-cache-update:%d-%d-%d-%d' % (level, zoom, x, y)
        tile_cache_update = cache.get(tile_cache_update_cache_key, None)
        if tile_cache_update is None:
            try:
                with open(last_update_filename) as f:
                    tile_cache_update = f.read()
            except FileNotFoundError:
                pass

        if tile_cache_update != base_cache_key:
            os.system('rm -rf '+os.path.join(tile_dirname, '*'))
        else:
            try:
                with open(tile_filename, 'rb') as f:
                    data = f.read()
            except FileNotFoundError:
                pass

    if data is None:
        renderer = MapRenderer(level, minx, miny, maxx, maxy, scale=2 ** zoom, access_permissions=access_permissions)
        image = renderer.render(ImageRenderEngine)
        data = image.render()

        if settings.CACHE_TILES:
            os.makedirs(tile_dirname, exist_ok=True)
            with open(tile_filename, 'wb') as f:
                f.write(data)
            with open(last_update_filename, 'w') as f:
                f.write(base_cache_key)
            cache.get(tile_cache_update_cache_key, base_cache_key, 60)

    response = HttpResponse(data, 'image/png')
    response['ETag'] = tile_etag
    response['Cache-Control'] = 'no-cache'
    response['Vary'] = 'Cookie'

    return response


@no_language()
@set_tile_access_cookie
def tile_access(request):
    response = HttpResponse(content_type='text/plain')
    response['Cache-Control'] = 'no-cache'
    return response


@etag(lambda *args, **kwargs: MapUpdate.current_processed_cache_key())
@no_language()
def map_history(request, level, mode, filetype):
    if not request.user.is_superuser:
        raise PermissionDenied
    level = get_object_or_404(Level, pk=level)

    if mode == 'composite' and level.on_top_of_id is not None:
        raise Http404

    history = MapHistory.open_level(level.pk, mode)
    if filetype == 'png':
        response = HttpResponse(content_type='image/png')
        history.to_image().save(response, format='PNG')
    elif filetype == 'data':
        response = HttpResponse(content_type='application/octet-stream')
        history.write(response)
    else:
        raise ValueError
    response['Cache-Control'] = 'no-cache'
    return response


@etag(lambda *args, **kwargs: MapUpdate.current_processed_cache_key())
@no_language()
def get_cache_package(request, filetype):
    enforce_tile_secret_auth(request)

    filename = os.path.join(settings.CACHE_ROOT, 'package.'+filetype)
    f = open(filename, 'rb')

    f.seek(0, os.SEEK_END)
    size = f.tell()
    f.seek(0)

    content_type = 'application/' + {'tar': 'x-tar', 'tar.gz': 'gzip', 'tar.xz': 'x-xz'}[filetype]

    response = StreamingHttpResponse(FileWrapper(f), content_type=content_type)
    response['Content-Length'] = size
    return response
