from django.core.cache import cache

from c3nav.mapdata.utils.cache.indexed import GeometryIndexed  # noqa
from c3nav.mapdata.utils.cache.maphistory import MapHistory  # noqa
from c3nav.mapdata.utils.cache.accessrestrictions import AccessRestrictionAffected  # noqa
from c3nav.mapdata.utils.cache.package import CachePackage  # noqa


def increment_cache_key(cache_key):
    try:
        cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 0, None)
