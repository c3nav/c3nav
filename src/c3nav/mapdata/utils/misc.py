import os

from django.conf import settings
from shapely.geometry import box
from shapely.ops import cascaded_union

from c3nav.mapdata.utils.cache import cache_result


@cache_result('c3nav__mapdata__dimensions')
def get_dimensions():
    # todo calculate this
    return (400, 240)


@cache_result('c3nav__mapdata__render_dimensions')
def get_render_dimensions():
    width, height = get_dimensions()
    return (width * settings.RENDER_SCALE, height * settings.RENDER_SCALE)


def get_render_path(filetype, level, mode, public):
    return os.path.join(settings.RENDER_ROOT,
                        '%s%s-level-%s.%s' % (('public-' if public else ''), mode, level, filetype))


def get_public_private_area(level):
    from c3nav.mapdata.models import AreaLocation

    width, height = get_dimensions()
    everything = box(0, 0, width, height)
    needs_permission = [location.geometry
                        for location in AreaLocation.objects.filter(level=level,
                                                                    routing_inclusion='needs_permission')]
    public_area = level.public_geometries.areas_and_doors.difference(cascaded_union(needs_permission))
    private_area = everything.difference(public_area)
    return public_area, private_area
