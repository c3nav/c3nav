import pickle
import threading
from dataclasses import dataclass
from typing import Self

from django.conf import settings

from c3nav.mapdata.models import MapUpdate
from c3nav.mapdata.models.geometry.space import RangingBeacon
from c3nav.routing.router import Router


@dataclass
class RangeLocatorBeacon:
    bssid: str
    x: int
    y: int
    z: int


@dataclass
class RangeLocator:
    filename = settings.CACHE_ROOT / 'rangelocator'

    beacons: dict[str, RangeLocatorBeacon]

    @classmethod
    def rebuild(cls, update):
        router = Router.load()

        # get beacons and calculate absoluze z coordinate
        beacons = {}
        for beacon in RangingBeacon.objects.all():
            beacons[beacon.bssid] = RangeLocatorBeacon(
                bssid=beacon.bssid,
                x=int(beacon.geometry.x * 100),
                y=int(beacon.geometry.y * 100),
                z=int(router.altitude_for_point(beacon.space_id, beacon.geometry) * 100),
            )

        locator = cls(beacons=beacons)
        pickle.dump(locator, open(cls.build_filename(update), 'wb'))
        return locator

    @classmethod
    def build_filename(cls, update):
        return settings.CACHE_ROOT / ('rangelocator_%s.pickle' % MapUpdate.build_cache_key(*update))

    @classmethod
    def load_nocache(cls, update):
        return pickle.load(open(cls.build_filename(update), 'rb'))

    cached = None
    cache_update = None
    cache_lock = threading.Lock()

    @classmethod
    def load(cls) -> Self:
        from c3nav.mapdata.models import MapUpdate
        update = MapUpdate.last_processed_update()
        if cls.cache_update != update:
            with cls.cache_lock:
                cls.cache_update = update
                cls.cached = cls.load_nocache(update)
        return cls.cached

    def locate(self, scan, permissions=None):
        return None
