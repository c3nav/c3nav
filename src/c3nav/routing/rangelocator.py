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
class RangeLocator:
    filename = settings.CACHE_ROOT / 'rangelocator'

    beacon_positions: np.array
    beacon_lookup: dict[str: int]

    @classmethod
    def rebuild(cls, update):
        router = Router.load()

        beacons = RangingBeacon.objects.all()

        locator = cls(
            beacon_positions=np.array(tuple(
                (
                    int(beacon.geometry.x * 100),
                    int(beacon.geometry.y * 100),
                    int((router.altitude_for_point(beacon.space_id, beacon.geometry) + float(beacon.altitude)) * 100),
                )
                for beacon in beacons
            )),
            beacon_lookup={beacon.bssid: i for i, beacon in enumerate(beacons)}
        )
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

    def locate(self, scan: dict[str, int], permissions=None):
        # get the i and peer for every peer that we actually know
        ranges = tuple(
            (i, peer) for i, peer in (
                (self.beacon_lookup.get(bssid, None), distance) for bssid, distance in scan.items()
            ) if i is not None
        )

        # get index of all known beacons
        beacons_i = tuple(i for i, peer in ranges)

        # create 2d array with x, y, z, distance as rows
        np_ranges = np.hstack((
            self.beacon_positions[tuple(i for i, distance in ranges), :],
            np.array(tuple(distance for i, distance in ranges)).reshape((-1, 1)),
        ))

        if np_ranges.shape[0] < 3:
            # can't get a good result from just two beacons
            # todo: maybe we can at least give… something?
            return None

        if np_ranges.shape[0] == 3:
            # TODO: three points aren't really enough for precise results? hm. maybe just a 2d fix then?
            pass

        # rating the guess by calculating the distances
        def rate_guess(guess):
            return scipy.linalg.norm(np_ranges[:, :3]-guess[:3], axis=1)*guess[3]-np_ranges[:, 3]

        # initial guess i the average of all beacons, with scale 1
        initial_guess = np.append(np.average(np_ranges[:, :3], axis=0), 1)

        # here the magic happens
        results = least_squares(rate_guess, initial_guess)

        # create result
        # todo: figure out level
        from c3nav.mapdata.models import Level
        location = CustomLocation(
            level=Level.objects.first(),
            x=results.x[0]/100,
            y=results.x[1]/100,
            permissions=(),
            icon='my_location'
        )

        print("measured ranges:", ", ".join(("%.2f" % i) for i in tuple(np_ranges[:, 3])))
        print("result ranges:", ", ".join(("%.2f" % i) for i in tuple(scipy.linalg.norm(np_ranges[:, :3] - results.x[:3], axis=1) * results.x[3])))
        print("height:", results.x[2])
        print("scale:", results.x[3])

        return location
