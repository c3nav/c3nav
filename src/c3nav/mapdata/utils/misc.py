import os

from django.conf import settings
from django.db.models import Max, Min

from c3nav.mapdata.models import Package
from c3nav.mapdata.utils.cache import cache_result


@cache_result('c3nav__mapdata__dimensions')
def get_dimensions():
    aggregate = Package.objects.all().aggregate(Max('right'), Min('left'), Max('top'), Min('bottom'))
    return (
        float(aggregate['right__max'] - aggregate['left__min']),
        float(aggregate['top__max'] - aggregate['bottom__min']),
    )


@cache_result('c3nav__mapdata__render_dimensions')
def get_render_dimensions():
    width, height = get_dimensions()
    return (width * settings.RENDER_SCALE, height * settings.RENDER_SCALE)


def get_render_path(filetype, level, mode, public):
    return os.path.join(settings.RENDER_ROOT,
                        '%s%s-level-%s.%s' % (('public-' if public else ''), mode, level, filetype))
