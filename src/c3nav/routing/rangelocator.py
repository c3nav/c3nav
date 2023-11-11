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

        dimensions = 2

        measured_ranges = np_ranges[:, 3]
        measured_ranges = measured_ranges / np.max(measured_ranges)

        # rating the guess by calculating the distances
        def rate_guess(guess):
            guessed_ranges = scipy.linalg.norm(np_ranges[:, :dimensions] - guess[:dimensions], axis=1)
            guessed_ranges /= np.max(guessed_ranges)
            diffs = guessed_ranges-measured_ranges
            if (diffs < -200).any():
                return diffs+100-np.clip(diffs, None, -200)*10
            return diffs

        # initial guess i the average of all beacons, with scale 1
        initial_guess = np.average(np_ranges[:, :dimensions], axis=0)

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
        print("result ranges:", ", ".join(
            ("%.2f" % i) for i in tuple(scipy.linalg.norm(np_ranges[:, :dimensions] - results.x[:dimensions], axis=1))
        ))
        if dimensions > 2:
            print("height:", results.x[2])
        # print("scale:", (factor or results.x[3]))

        return location
