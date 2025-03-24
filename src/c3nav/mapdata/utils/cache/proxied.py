from collections import OrderedDict
from contextvars import ContextVar

from django.conf import settings
from django.core.cache import cache

from c3nav.mapdata.utils.cache.types import MapUpdateTuple


class NoneFromCache:
    pass


class LocalCacheProxy:
    # django cache, buffered using a LRU cache
    # only usable for stuff that never needs to know about changes made by other cache clients, obviously
    # todo: ensure expire?
    def __init__(self, maxsize=128):
        self._maxsize = maxsize
        self._mapupdate = None
        self._items: ContextVar[OrderedDict] = ContextVar("cache items")
        # do not use a default of a dict, this can lead to same instance in different contexts
        # we don't particularly care about this for LocalCacheProxy,
        # but we DEFINITELY care about this for the local request cache.
        # Most importantly, this is why the clear function always sets a new dictionary to be extra sure.

    def _get_items(self):
        try:
            return self._items.get()
        except LookupError:
            self.clear()
            return self._items.get()

    def get(self, key, default=None):
        if self._mapupdate is None:
            self._check_mapupdate()
        try:
            # first check out cache
            result = self._get_items()[key]
        except KeyError:
            # not in our cache
            result = cache.get(key, default=NoneFromCache)
            if result is not NoneFromCache:
                self._get_items()[key] = result
                self._prune()
            else:
                result = default
        else:
            self._get_items().move_to_end(key, last=True)
        return result

    def _prune(self):
        # remove old items
        while len(self._get_items()) > self._maxsize:
            self._get_items().pop(next(iter(self._get_items().keys())))

    def _check_mapupdate(self):
        # todo: thanks to enable_globally() we shouldn't need this any more
        from c3nav.mapdata.models import MapUpdate
        mapupdate = MapUpdate.last_update()
        if self._mapupdate != mapupdate:
            self.clear()
            self._mapupdate = mapupdate

    enabled = False
    @classmethod
    def enable_globally(cls):
        """
        This gets called when the per request cache middleware is loaded.
        We don't want local cache proxies to work outside of requests.
        """
        LocalCacheProxy.enabled = True

    def set(self, key, value, expire):
        self._check_mapupdate()
        cache.set(key, value, expire)
        if LocalCacheProxy.enabled:
            self._get_items()[key] = value
        self._prune()

    def clear(self):
        self._items.set(OrderedDict())

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