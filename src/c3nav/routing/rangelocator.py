import pickle
import threading
from dataclasses import dataclass
from pprint import pprint
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

    def get_xyz(self, address) -> tuple[int, int, int] | None:
        try:
            i = self.beacon_lookup[address]
        except KeyError:
            return None
        return tuple(self.beacon_positions[i])

    def get_all_xyz(self):
        return {
            address: tuple(self.beacon_positions[i].tolist())
            for address, i in self.beacon_lookup.items()
        }

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

    def locate(self, ranges: dict[str, int], permissions=None, orig_addr=None):
        pprint(ranges)
        # get the i and peer for every peer that we actually know
        relevant_ranges = tuple(
            (i, distance) for i, distance in (
                (self.beacon_lookup.get(bssid, None), distance) for bssid, distance in ranges.items()
            ) if i is not None
        )

        relevant_positions = self.beacon_positions[tuple(i for i, _ in relevant_ranges), :]
        mean = np.mean(relevant_positions, axis=0)
        relevant_positions = relevant_positions

        # create 2d array with x, y, z, distance as rows
        np_ranges = np.hstack((
            relevant_positions,
            np.array(tuple(distance for i, distance in relevant_ranges)).reshape((-1, 1)),
        ))

        print(np_ranges)

        if np_ranges.shape[0] < 3:
            # can't get a good result from just two beacons
            # todo: maybe we can at least give… something?
            print('less than 3 ranges, can\'t do ranging')
            return None

        if np_ranges.shape[0] == 3 and 0:
            print('2D trilateration')
            dimensions = 2
        else:
            print('3D trilateration')
            dimensions = 3

        measured_ranges = np_ranges[:, 3]
        print('a', measured_ranges)
        #measured_ranges[measured_ranges<1] = 1
        print('b', measured_ranges)

        # rating the guess by calculating the distances
        def diff_func(guess):
            result = scipy.linalg.norm(np_ranges[:, :dimensions] - guess[:dimensions], axis=1) - measured_ranges
            #print(result)
            return result
            # factors = scipy.linalg.norm(np_ranges[:, :dimensions] - guess[:dimensions], axis=1) / measured_ranges
            # return factors - np.mean(factors)

        def cost_func(guess):
            result = np.abs(diff_func(guess))
            result[result<300] = result[result<300]/3+200
            return result

        # initial guess i the average of all beacons, with scale 1
        initial_guess = np.average(np_ranges[:, :dimensions], axis=0)

        # here the magic happens
        results = least_squares(
            fun=cost_func,
            #jac="3-point",
            loss="linear",
            bounds=(
                np.min(self.beacon_positions[:, :dimensions], axis=0) - np.array([200, 200, 100])[:dimensions],
                np.max(self.beacon_positions[:, :dimensions], axis=0) + np.array([200, 200, 100])[:dimensions],
            ),
            x0=initial_guess,
        )

        # create result
        # todo: figure out level
        result_pos = results.x
        from c3nav.mapdata.models import Level
        location = CustomLocation(
            level=Level.objects.first(),
            x=result_pos[0]/100,
            y=result_pos[1]/100,
            permissions=(),
            icon='my_location'
        )
        location.z = result_pos[2]/100

        pprint(relevant_ranges)

        orig_xyz = None
        print('orig_addr', orig_addr)
        if orig_addr:
            orig_xyz = self.get_xyz(orig_addr)
            if orig_xyz:
                orig_xyz = np.array(orig_xyz)

        print()
        print("result:", ", ".join(("%.2f" % i) for i in tuple(result_pos)))
        if orig_xyz is not None:
            print("correct:", ", ".join(("%.2f" % i) for i in tuple(orig_xyz)))
            print("diff:", ", ".join(("%.2f" % i) for i in tuple(orig_xyz-result_pos)))
        print()
        print("measured ranges:", ", ".join(("%.2f" % i) for i in tuple(np_ranges[:, 3])))
        print("result ranges:", ", ".join(
            ("%.2f" % i) for i in tuple(scipy.linalg.norm(np_ranges[:, :dimensions] - result_pos[:dimensions], axis=1))
        ))
        if orig_xyz is not None:
            print("correct ranges:", ", ".join(
                ("%.2f" % i) for i in tuple(scipy.linalg.norm(np_ranges[:, :dimensions] - orig_xyz[:dimensions], axis=1))
            ))
        print()
        print("diff result-measured:", ", ".join(
            ("%.2f" % i) for i in
            tuple(diff_func(result_pos))
        ))
        if orig_xyz is not None:
            print("diff correct-measured:", ", ".join(
                ("%.2f" % i) for i in
                tuple(diff_func(orig_xyz))
            ))

        def print_cost(title, pos):
            cost = cost_func(pos)
            print(title, ", ".join(
                ("%.2f" % i) for i in cost
            ), '=', np.sum(cost**2))
        print_cost("cost:", result_pos)
        if orig_xyz is not None:
            print_cost("cost of correct position:", orig_xyz)
        if dimensions > 2:
            print("height:", result_pos[2])
        # print("scale:", (factor or results.x[3]))

        return location
