import base64
import os
from collections import Counter
from itertools import chain
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
from shapely import LineString, Point, box, unary_union

from c3nav.mapdata.middleware import no_language
from c3nav.mapdata.models import Level, MapUpdate
from c3nav.mapdata.models.update import MapUpdateJob
from c3nav.mapdata.permissions import MapPermissionsFromRequest
from c3nav.mapdata.render.engines import ImageRenderEngine
from c3nav.mapdata.render.engines.base import FillAttribs, StrokeAttribs
from c3nav.mapdata.render.renderer import MapRenderer
from c3nav.mapdata.schemas.model_base import LocationPoint
from c3nav.mapdata.utils.cache import CachePackage, MapHistory
from c3nav.mapdata.locations import LocationManager
from c3nav.mapdata.utils.geometry import merge_bounds
from c3nav.mapdata.utils.tiles import (build_access_cache_key, build_base_cache_key, build_tile_access_cookie,
                                       build_tile_etag, get_tile_bounds, parse_tile_access_cookie)

PREVIEW_HIGHLIGHT_FILL_OPACITY = 0.1
PREVIEW_HIGHLIGHT_STROKE_WIDTH = 0.5
PREVIEW_IMG_WIDTH = 1200
PREVIEW_IMG_HEIGHT = 628
PREVIEW_MIN_Y = 100


def set_tile_access_cookie(request, response):
    access_permissions = MapPermissionsFromRequest(request).access_restrictions
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


def bounds_for_preview(geometry, cache_package):
    bounds = geometry.bounds

    if not cache_package.bounds_valid(bounds[0], bounds[1], bounds[2], bounds[3]):
        raise Http404

    bounds_width = bounds[2] - bounds[0]
    bounds_height = bounds[3] - bounds[1]

    height = PREVIEW_MIN_Y
    if height < bounds_height:
        height = bounds_height + 10
    width = height * PREVIEW_IMG_WIDTH / PREVIEW_IMG_HEIGHT
    if width < bounds_width:
        width = bounds_width + 10
    height = width * PREVIEW_IMG_HEIGHT / PREVIEW_IMG_WIDTH

    dx = width - bounds_width
    dy = height - bounds_height
    minx = int(bounds[0] - dx / 2)
    maxx = int(bounds[2] + dx / 2)
    miny = int(bounds[1] - dy / 2)
    maxy = int(bounds[3] + dy / 2)
    img_scale = PREVIEW_IMG_HEIGHT / height

    return minx, miny, maxx, maxy, img_scale


def cache_preview(request, key, last_update, render_fn):
    import binascii
    import hashlib
    base_cache_key = build_base_cache_key(last_update)
    preview_etag = '"' + binascii.b2a_base64(hashlib.sha256(
        ('%s:%s:%s' % (key, base_cache_key, settings.SECRET_TILE_KEY[:26])).encode()
    ).digest()[:15], newline=False).decode() + '"'
    if request.META.get('HTTP_IF_NONE_MATCH') == preview_etag:
        return HttpResponseNotModified()

    data = None
    if settings.CACHE_PREVIEWS:
        previews_directory = settings.PREVIEWS_ROOT / key
        last_update_file = previews_directory / 'last_update'
        preview_file = previews_directory / 'preview.png'

        preview_cache_update_cache_key = 'mapdata:preview-cache-update:%s' % key
        preview_cache_update = cache.get(preview_cache_update_cache_key, None)
        if preview_cache_update is None:
            try:
                preview_cache_update = last_update_file.read_text()
            except FileNotFoundError:
                pass

        if preview_cache_update != base_cache_key:
            try:
                old_previews_directory = previews_directory.rename(previews_directory.parent /
                                                                   (previews_directory.name + '_old'))
                rmtree(old_previews_directory)
            except FileNotFoundError:
                pass
        else:
            try:
                data = preview_file.read_bytes()
            except FileNotFoundError:
                pass

    if data is None:
        data = render_fn()
        if settings.CACHE_PREVIEWS:
            os.makedirs(previews_directory, exist_ok=True)
            preview_file.write_bytes(data)
            last_update_file.write_text(base_cache_key)
            cache.set(preview_cache_update_cache_key, base_cache_key, 60)

    response = HttpResponse(data, 'image/png')
    response['ETag'] = preview_etag
    response['Cache-Control'] = 'no-cache'
    response['Vary'] = 'Cookie'
    return response


@no_language()
def preview_location(request, slug):
    from c3nav.site.views import check_location

    location = check_location(slug, None)
    # todo: handle redirect?
    highlight = True
    if location is None:
        raise Http404

    slug = location.effective_slug

    # collect all the sublocations
    # todo: handle dynamic locations
    locations = {
        location.effective_slug: location
    }
    locations_to_check = [location]
    while locations_to_check:
        for location_id in locations_to_check.pop().locations:
            sublocation = LocationManager.get(location_id)
            if sublocation.effective_slug not in locations:
                locations[sublocation.effective_slug] = sublocation
                locations_to_check.append(sublocation)

    # are there any points?
    points: list[LocationPoint] = list(chain(
        *(loc.points for loc in locations),
    ))
    if points:
        # there are points, then this is what we will show and highlight
        counts = Counter([point[0] for point in points])
        level_id = counts.most_common(1)[0][0]
        highlight = True
        geometries = list(chain(*(
            loc.geometries_or_points_by_level.get(level_id, ()) for loc in locations
        )))
    else:
        # there are no points, so we will show a bounding box of the biggest level
        boxes = {level_id: box(*chain(*bounds))
                 for level_id, bounds in merge_bounds(*(loc.bounds for loc in locations))}
        if not boxes:
            raise Http404
        level_id, bbox = max(boxes.items(), key=lambda item: item[1].area)
        geometries = [bbox]

    cache_package = CachePackage.open_cached()

    from c3nav.mapdata.utils.geometry import unwrap_geom
    geometries = [geometry.buffer(1) if isinstance(geometry, Point) else unwrap_geom(geometry) for geometry in
                  geometries]

    minx, miny, maxx, maxy, img_scale = bounds_for_preview(unary_union(geometries), cache_package)

    theme = None if settings.DEFAULT_THEME == 0 else settings.DEFAULT_THEME  # previews use the default theme

    level_data = cache_package.levels.get((level_id, theme))
    if level_data is None:
        raise Http404

    def render_preview():
        renderer = MapRenderer(level_id, minx, miny, maxx, maxy, scale=img_scale, access_permissions=set())
        image = renderer.render(ImageRenderEngine, theme)
        if highlight:
            from c3nav.mapdata.render.theme import ColorManager
            color_manager = ColorManager.for_theme(theme)
            for geometry in geometries:
                image.add_geometry(geometry,
                                   fill=FillAttribs(color_manager.highlight, PREVIEW_HIGHLIGHT_FILL_OPACITY),
                                   stroke=StrokeAttribs(color_manager.highlight, PREVIEW_HIGHLIGHT_STROKE_WIDTH),
                                   category='highlight')
        return image.render()

    return cache_preview(request, slug, level_data.history.last_update(minx, miny, maxx, maxy), render_preview)


@no_language()
def preview_route(request, slug, slug2):
    # todo: allow a cache response without getting the route again
    from c3nav.routing.router import Router
    from c3nav.routing.models import RouteOptions
    from c3nav.routing.exceptions import NotYetRoutable
    from c3nav.routing.exceptions import LocationUnreachable
    from c3nav.routing.exceptions import NoRouteFound
    from c3nav.site.views import check_location
    from c3nav.mapdata.utils.geometry import unwrap_geom
    origin = check_location(slug, None)
    destination = check_location(slug2, None)
    if origin is None or destination is None:
        raise Http404()
    try:
        route = Router.load().get_route(origin=origin,
                                        destination=destination,
                                        options=RouteOptions())
    except NotYetRoutable:
        raise Http404()
    except LocationUnreachable:
        raise Http404()
    except NoRouteFound:
        raise Http404()

    route_items = [route.router.nodes[x] for x in route.path_nodes]
    route_points = [(item.point.x, item.point.y, route.router.spaces[item.space].level_id) for item in route_items]

    origin_level = route_points[0][1]

    lines = []
    line = None
    for x, y, level in route_points:
        if line is None and level == origin_level:
            line = [(x, y)]
        elif line is not None and level == origin_level:
            line.append((x, y))
        elif line is not None and level != origin_level:
            if len(line) > 1:
                lines.append(line)
            line = None
    if line is not None and len(line) > 1:
        lines.append(line)

    route_geometries = [LineString(line) for line in lines]

    origin_geometry = [
        geometry.buffer(1) if isinstance(geometry, Point) else unwrap_geom(geometry)
        for geometry in route.origin.location.geometries_or_points_by_level.get(origin_level, [])
    ]
    destination_geometry = [
        geometry.buffer(1) if isinstance(geometry, Point) else unwrap_geom(geometry)
        for geometry in route.detination.location.geometries_or_points_by_level.get(origin_level, [])
    ]

    all_geoms = [
        *route_geometries,
        *origin_geometry,
        *destination_geometry,
    ]
    combined_geometry = unary_union([x for x in all_geoms if x is not None])

    cache_package = CachePackage.open_cached()

    minx, miny, maxx, maxy, img_scale = bounds_for_preview(combined_geometry, cache_package)

    theme = None if settings.DEFAULT_THEME == 0 else settings.DEFAULT_THEME  # previews use the default theme

    level_data = cache_package.levels.get((origin_level, theme))
    if level_data is None:
        raise Http404

    def render_preview():
        renderer = MapRenderer(origin_level, minx, miny, maxx, maxy, scale=img_scale, access_permissions=set())
        image = renderer.render(ImageRenderEngine, theme)
        from c3nav.mapdata.render.theme import ColorManager
        color_manager = ColorManager.for_theme(theme)
        for geometry in origin_geometry:
            image.add_geometry(geometry,
                               fill=FillAttribs(color_manager.highlight, PREVIEW_HIGHLIGHT_FILL_OPACITY),
                               stroke=StrokeAttribs(color_manager.highlight, PREVIEW_HIGHLIGHT_STROKE_WIDTH),
                               category='highlight')
        for geometry in destination_geometry:
            image.add_geometry(geometry,
                               fill=FillAttribs(color_manager.highlight, PREVIEW_HIGHLIGHT_FILL_OPACITY),
                               stroke=StrokeAttribs(color_manager.highlight, PREVIEW_HIGHLIGHT_STROKE_WIDTH),
                               category='highlight')

        for geom in route_geometries:
            image.add_geometry(geom,
                               stroke=StrokeAttribs(color_manager.highlight, PREVIEW_HIGHLIGHT_STROKE_WIDTH),
                               category='route')
        return image.render()

    return cache_preview(request, f'{slug}:{slug2}', level_data.history.last_update(minx, miny, maxx, maxy),
                         render_preview)


@no_language()
def tile(request, level, zoom, x, y, theme, access_permissions: Optional[set] = None):
    if access_permissions is not None:
        enforce_tile_secret_auth(request)
    elif settings.TILE_CACHE_SERVER:
        return HttpResponse('use %s instead of /map/' % settings.TILE_CACHE_SERVER,
                            status=400, content_type='text/plain')

    processed_geometry_update = str(MapUpdateJob.last_successful_update("mapdata.recalculate_geometries")[0])

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

    theme = None if theme == 0 else int(theme)
    theme_key = str(theme)

    # get level
    level = int(level)
    level_data = cache_package.levels.get((level, theme))
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
            access_permissions &= set(level_data.restrictions[minx:maxx, miny:maxy]) | level_data.global_restrictions
    else:
        access_permissions = access_permissions - {0}

    if not all((r in access_permissions) for r in level_data.global_restrictions):
        raise Http404

    # build cache keys
    last_update = level_data.history.last_update(minx, miny, maxx, maxy)
    base_cache_key = build_base_cache_key(last_update)
    access_cache_key = build_access_cache_key(access_permissions)

    # check browser cache
    tile_etag = build_tile_etag(level, zoom, x, y, theme_key, base_cache_key, access_cache_key,
                                settings.SECRET_TILE_KEY)
    if_none_match = request.META.get('HTTP_IF_NONE_MATCH')
    if if_none_match == tile_etag:
        return HttpResponseNotModified()

    data = None
    tile_directory, last_update_file, tile_file, tile_cache_update_cache_key = '', '', '', ''

    # get tile cache last update
    if settings.CACHE_TILES:
        tile_directory = settings.TILES_ROOT / str(level) / str(zoom) / str(x) / str(y) / access_cache_key
        last_update_file = tile_directory / 'last_update'
        tile_file = tile_directory / f'{theme_key}.png'

        # get tile cache last update
        tile_cache_update_cache_key = 'mapdata:tile-cache-update:%d-%d-%d-%d' % (level, zoom, x, y)
        tile_cache_update = cache.get(tile_cache_update_cache_key, None)
        if tile_cache_update is None:
            try:
                tile_cache_update = last_update_file.read_text()
            except FileNotFoundError:
                pass

        if tile_cache_update != base_cache_key:
            try:
                old_tile_directory = tile_directory.rename(tile_directory.parent /
                                                           (tile_directory.name + '_old_tile_dir'))
                rmtree(old_tile_directory)
            except FileNotFoundError:
                pass
        else:
            try:
                data = tile_file.read_bytes()
            except FileNotFoundError:
                pass

    if data is None:
        renderer = MapRenderer(level, minx, miny, maxx, maxy, scale=2 ** zoom, access_permissions=access_permissions)
        image = renderer.render(ImageRenderEngine, theme=theme)
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
    if access_permissions is not None:
        response['X-Processed-Geometry-Update'] = processed_geometry_update

    return response


@etag(lambda *args, **kwargs: MapUpdateJob.last_successful_update("mapdata.recalculate_geometries").cache_key)
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


@etag(lambda *args, **kwargs: MapUpdateJob.last_successful_update("mapdata.recalculate_geometries").cache_key)
@no_language()
def get_cache_package(request, filetype):
    processed_geometry_update = str(MapUpdateJob.last_successful_update("mapdata.recalculate_geometries")[0])

    enforce_tile_secret_auth(request)

    filename = 'package.' + filetype
    cache_package = CachePackage.get_filename(
        MapUpdateJob.last_successful_update("mapdata.recalculate_geometries").cache_key,
        filetype[4:] if filetype != 'tar' else None
    )
    try:
        size = cache_package.stat().st_size
        f = cache_package.open('rb')
    except FileNotFoundError:
        raise Http404

    content_type = 'application/' + {'tar': 'x-tar', 'tar.gz': 'gzip', 'tar.xz': 'x-xz', 'tar.zst': 'zstd'}[filetype]
    response = StreamingHttpResponse(FileWrapper(f), content_type=content_type)
    # The next 2 lines cause django to use the wsgi.file_wrapper if provided by the wsgi server.
    response.file_to_stream = f
    response.block_size = 8192
    response['Content-Length'] = size
    if content_disposition := content_disposition_header(False, filename):
        response["Content-Disposition"] = content_disposition
    response['X-Processed-Geometry-Update'] = processed_geometry_update
    return response


def prometheus_exporter(request):
    """Exports the API metrics for Prometheus"""

    import prometheus_client
    from django_prometheus.exports import ExportToDjangoView
    from c3nav.mapdata.metrics import REGISTRY
    metrics_page = prometheus_client.generate_latest(REGISTRY)
    response = ExportToDjangoView(request)
    response.content += metrics_page
    return response
