from collections import OrderedDict

from django.core.cache import cache
from django.conf import settings


class NoneFromCache:
    pass


class LocalCacheProxy:
    # django cache, buffered using a LRU cache
    # only usable for stuff that never changes, obviously
    # todo: ensure thread-safety, compatible with async + daphne etc
    # todo: ensure expire?
    def __init__(self, maxsize=128):
        self._maxsize = maxsize
        self._mapupdate = None
        self._items = OrderedDict()

    def get(self, key, default=None):
        if self._mapupdate is None:
            self._check_mapupdate()
        try:
            # first check out cache
            result = self._items[key]
        except KeyError:
            # not in our cache
            result = cache.get(key, default=NoneFromCache)
            if result is not NoneFromCache:
                self._items[key] = result
                self._prune()
            else:
                result = default
        else:
            self._items.move_to_end(key, last=True)
        return result

    def _prune(self):
        # remove old items
        while len(self._items) > self._maxsize:
            self._items.pop(next(iter(self._items.keys())))

    def _check_mapupdate(self):
        # todo: would be nice to not need this… why do we need this?

        from c3nav.mapdata.models import MapUpdate
        mapupdate = MapUpdate.current_cache_key()
        if self._mapupdate != mapupdate:
            self._items = OrderedDict()
            self._mapupdate = mapupdate

    def set(self, key, value, expire):
        self._check_mapupdate()
        cache.set(key, value, expire)
        self._items[key] = value
        self._prune()

    def clear(self):
        self._items.clear()


class RequestLocalCacheProxy(LocalCacheProxy):
    """ this is a subclass without prune, to be cleared after every request """
    def _prune(self):
        pass

    def _check_mapupdate(self):
        pass


# todo: we want multiple copies of this
per_request_cache = RequestLocalCacheProxy(maxsize=settings.CACHE_SIZE_LOCATIONS)