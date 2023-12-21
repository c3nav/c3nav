import base64
import os
from shutil import rmtree
from typing import Optional
from wsgiref.util import FileWrapper

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, HttpResponseNotModified, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils.http import content_disposition_header
from django.views.decorators.http import etag

from c3nav.mapdata.middleware import no_language
from c3nav.mapdata.models import Level, MapUpdate
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.render.engines import ImageRenderEngine
from c3nav.mapdata.render.renderer import MapRenderer
from c3nav.mapdata.utils.cache import CachePackage, MapHistory
from c3nav.mapdata.utils.tiles import (build_access_cache_key, build_base_cache_key, build_tile_access_cookie,
                                       build_tile_etag, get_tile_bounds, parse_tile_access_cookie)


def set_tile_access_cookie(request, response):
    access_permissions = AccessPermission.get_for_request(request)
    if access_permissions:
        cookie = build_tile_access_cookie(access_permissions, settings.SECRET_TILE_KEY)
        response.set_cookie(settings.TILE_ACCESS_COOKIE_NAME, cookie, max_age=60,
                            domain=settings.TILE_ACCESS_COOKIE_DOMAIN,
                            httponly=settings.TILE_ACCESS_COOKIE_HTTPONLY,
                            secure=settings.TILE_ACCESS_COOKIE_SECURE,
                            samesite=settings.TILE_ACCESS_COOKIE_SAMESITE)
    else:
        response.delete_cookie(settings.TILE_ACCESS_COOKIE_NAME)
    response['Cache-Control'] = 'no-cache'


encoded_tile_secret = base64.b64encode(settings.SECRET_TILE_KEY.encode()).decode()


def enforce_tile_secret_auth(request):
    x_tile_secret = request.META.get('HTTP_X_TILE_SECRET')
    if x_tile_secret:
        if x_tile_secret != encoded_tile_secret:
            raise PermissionDenied
    elif not request.user.is_superuser:
        raise PermissionDenied


@no_language()
def tile(request, level, zoom, x, y, access_permissions: Optional[set] = None):
    if access_permissions is not None:
        enforce_tile_secret_auth(request)
    elif settings.TILE_CACHE_SERVER:
        return HttpResponse('use %s instead of /map/' % settings.TILE_CACHE_SERVER,
                            status=400, content_type='text/plain')

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
            access_permissions &= set(level_data.restrictions[minx:maxx, miny:maxy])
    else:
        access_permissions = access_permissions - {0}

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
    tile_directory, last_update_file, tile_file, tile_cache_update_cache_key = '', '', '', ''

    # get tile cache last update
    if settings.CACHE_TILES:
        tile_directory = settings.TILES_ROOT / str(level) / str(zoom) / str(x) / str(y)
        last_update_file = tile_directory / 'last_update'
        tile_file = tile_directory / (access_cache_key+'.png')

        # get tile cache last update
        tile_cache_update_cache_key = 'mapdata:tile-cache-update:%d-%d-%d-%d' % (level, zoom, x, y)
        tile_cache_update = cache.get(tile_cache_update_cache_key, None)
        if tile_cache_update is None:
            try:
                tile_cache_update = last_update_file.read_text()
            except FileNotFoundError:
                pass

        if tile_cache_update != base_cache_key:
            if tile_directory.exists():
                rmtree(tile_directory)
        else:
            try:
                data = tile_file.read_bytes()
            except FileNotFoundError:
                pass

    if data is None:
        renderer = MapRenderer(level, minx, miny, maxx, maxy, scale=2 ** zoom, access_permissions=access_permissions)
        image = renderer.render(ImageRenderEngine)
        data = image.render()

        if settings.CACHE_TILES:
            os.makedirs(tile_directory, exist_ok=True)
            tile_file.write_bytes(data)
            last_update_file.write_text(base_cache_key)
            cache.set(tile_cache_update_cache_key, base_cache_key, 60)

    response = HttpResponse(data, 'image/png')
    response['ETag'] = tile_etag
    response['Cache-Control'] = 'no-cache'
    response['Vary'] = 'Cookie'

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

    filename = 'package.' + filetype
    cache_package = settings.CACHE_ROOT / filename
    try:
        size = cache_package.stat().st_size
        f = cache_package.open('rb')
    except FileNotFoundError:
        raise Http404

    content_type = 'application/' + {'tar': 'x-tar', 'tar.gz': 'gzip', 'tar.xz': 'x-xz', 'tar.zst': 'zstd'}[filetype]
    response = StreamingHttpResponse(FileWrapper(f), content_type=content_type)
    #response.file_to_stream = f  # This causes django to use the  wsgi.file_wrapper if provided by the wsgi server.
    response['Content-Length'] = size
    if content_disposition := content_disposition_header(False, filename):
        response["Content-Disposition"] = content_disposition
    return response
