from collections import OrderedDict

from django.conf import settings
from django.core.cache import cache

from c3nav.mapdata.utils.cache.types import MapUpdateTuple


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
        mapupdate = MapUpdate.last_update()
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

    def delete(self, key: str):
        cache.delete(key)
        self._items.pop(key, None)


class RequestLocalCacheProxy(LocalCacheProxy):
    """ this is a subclass without prune, to be cleared after every request """
    def _prune(self):
        pass

    def _check_mapupdate(self):
        pass


class VersionedCacheProxy:
    # django cache, but with version
    def __init__(self, orig_cache):
        self.orig_cache = orig_cache

    def _convert_key(self, key: str) -> str:
        return f"{key}:versioned"

    def get(self, version: MapUpdateTuple, key: str, default=None):
        # needs to be MapUpdateTuple because we compare it below
        result = self.orig_cache.get(self._convert_key(key), default=None)
        if result is None:
            return default
        if result[0] < version:
            return default
        return result[1]

    def set(self, version: MapUpdateTuple, key: str, value, expire):
        self.orig_cache.set(self._convert_key(key), (version, value), expire)

    def delete(self, key: str):
        self.orig_cache.delete(key)


versioned_cache = VersionedCacheProxy(cache)
versioned_proxied_cache = VersionedCacheProxy(LocalCacheProxy(maxsize=128))

# todo: we want multiple copies of this?
per_request_cache = RequestLocalCacheProxy(maxsize=settings.CACHE_SIZE_LOCATIONS)
versioned_per_request_cache = VersionedCacheProxy(per_request_cache)