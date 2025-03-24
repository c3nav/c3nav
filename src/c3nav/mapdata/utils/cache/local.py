from collections import OrderedDict
from contextvars import ContextVar

from django.core.cache import cache
from django.conf import settings


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


class RequestLocalCacheProxy(LocalCacheProxy):
    """ this is a subclass without prune, to be cleared after every request """
    def _prune(self):
        pass

    def _check_mapupdate(self):
        pass


# todo: we want multiple copies of this
per_request_cache = RequestLocalCacheProxy(maxsize=settings.CACHE_SIZE_LOCATIONS)