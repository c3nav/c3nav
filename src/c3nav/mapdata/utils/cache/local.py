from collections import OrderedDict

from django.core.cache import cache

from c3nav.mapdata.models import MapUpdate


class NoneFromCache:
    pass


class LocalCacheProxy:
    # django cache, buffered using a LRU cache
    # only usable for stuff that never changes, obviously
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
        mapupdate = MapUpdate.current_cache_key()
        if self._mapupdate != mapupdate:
            self._items = OrderedDict()
            self._mapupdate = mapupdate

    def set(self, key, value, expire):
        self._check_mapupdate()
        cache.set(key, value, expire)
        self._items[key] = value
        self._prune()
