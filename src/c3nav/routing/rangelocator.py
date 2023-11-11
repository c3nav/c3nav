import pickle
import threading
from dataclasses import dataclass
from typing import Self

import numpy as np
import scipy
from django.conf import settings
from scipy.optimize import least_squares

from c3nav.mapdata.models import MapUpdate
from c3nav.mapdata.models.geometry.space import RangingBeacon
from c3nav.mapdata.utils.locations import CustomLocation
from c3nav.mesh.messages import MeshMessageType
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
                z=int((router.altitude_for_point(beacon.space_id, beacon.geometry)+float(beacon.altitude)) * 100),
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
        position = RangingBeacon.objects.select_related('space__level').first()
        location = CustomLocation(
            level=position.space.level,
            x=position.geometry.x,
            y=position.geometry.y,
            permissions=(),
            icon='my_location'
        )

        from c3nav.mesh.models import MeshNode
        try:
            node = MeshNode.objects.prefetch_last_messages(MeshMessageType.LOCATE_RANGE_RESULTS).get(
                address="d4:f9:8d:2d:0d:f1"
            )
        except MeshNode.DoesNotExist:
            raise
        msg = node.last_messages[MeshMessageType.LOCATE_RANGE_RESULTS]

        np_data = []
        for range in msg.parsed.ranges:
            try:
                beacon = self.beacons[range.peer]
            except KeyError:
                continue
            np_data.append((beacon.x, beacon.y, beacon.z, range.distance))
        if len(np_data) < 3:
            return {
                "ranges": msg.parsed.tojson(msg.parsed)["ranges"],
                "datetime": msg.datetime,
                "location": None,
            }
        np_ranges = np.array(np_data)

        def rate_guess(guess):
            #print(guess)
            #print(np_ranges[:, :3], guess[:3])
            #print([float(i) for i in results.x])
            return scipy.linalg.norm(np_ranges[:, :3]-guess[:3], axis=1)*guess[3]-np_ranges[:, 3]

        initial_guess = np.append(np.average(np_ranges[:, :3], axis=0), 1)

        results = least_squares(rate_guess, initial_guess)
        #print(results)
        #print([float(i) for i in results.x])

        from pprint import pprint
        pprint(msg.parsed.tojson(msg.parsed)["ranges"])
        location = CustomLocation(
            level=position.space.level,
            x=results.x[0]/100,
            y=results.x[1]/100,
            permissions=(),
            icon='my_location'
        )

        print("measured ranges:", ", ".join(("%.2f" % i) for i in tuple(np_ranges[:, 3])))
        print("result ranges:", ", ".join(("%.2f" % i) for i in tuple(scipy.linalg.norm(np_ranges[:, :3] - results.x[:3], axis=1) * results.x[3])))
        print("height:", results.x[2])
        print("scale:", results.x[3])

        return {
            "ranges": msg.parsed.tojson(msg.parsed)["ranges"],
            "datetime": msg.datetime,
            "location": location.serialize()
        }
