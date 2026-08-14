import time
import traceback
from dataclasses import fields
from typing import cast, Iterable

import numpy as np
from django.core.management.base import BaseCommand
from scipy.optimize import minimize, basinhopping, differential_evolution

# this is weird but needed so scipy can do multiprocessing
import django
django.setup()

from c3nav.mapdata.models.geometry.space import BeaconMeasurement
from c3nav.routing.locator import Locator, RangeLocateKnobs
from c3nav.routing.schemas import LocateWifiPeerSchema


class Command(BaseCommand):
    help = 'train range-based positioning knobs'

    @staticmethod
    def cost_func(guess, scans: list[list[LocateWifiPeerSchema]], correct_xyz, costs: list,
                  default_values, from_i, to_i):


        args = default_values[:from_i] + tuple(guess) + default_values[to_i:]

        locator = Locator.load()

        print(".", end="", flush=True)
        knobs = RangeLocateKnobs(*args)
        if not knobs.is_valid():
            pass #return np.inf
        results = []
        made = []
        starttime = time.time()
        for space_id, scan in scans:
            try:
                scan_data = locator.convert_raw_scan_data(scan)
                result = locator.raw_locate_range(scan_data, debug=False, knobs=knobs)
            except:
                traceback.print_exc()
                raise
            if result is None:
                made.append(False)
            else:
                made.append(True)
                results.append(result.xyz)
        duration = (time.time()-starttime) / len([i for i in made if i])

        offset_xyz = correct_xyz[tuple(made), :] - np.array(results)
        accuracies = np.linalg.norm(offset_xyz[:, :2], axis=1)
        accuracies = np.sort(accuracies)
        cost = np.sum(accuracies[:int(accuracies.shape[0]*0.9)] ** 2) / len(offset_xyz)
        #cost *= duration**2
        costs.append(cost)
        names = tuple(f.name for f in fields(RangeLocateKnobs))
        if cost == min(costs):
            print("\n")
            print(", ".join(f"{name}={float(i):.6f}" for name, i in zip(names[from_i:], guess)))
            sorted_accuracies = list(accuracies)
            last_target = 0
            for i, accuracy_2d in enumerate(sorted_accuracies, start=1):
                current_target = int(i / len(sorted_accuracies) * 10)
                if last_target != current_target:
                    last_target = current_target
                    print(f" - {current_target * 10}% are 2D accurate <= {accuracy_2d / 100:.1f} m")
            print(f"avg duration: {duration*1000:.2f}ms")
            #print(f"Original cost: {costs[0]:.2f}")
            print(f"Cost now: {cost:.2f} ({"better" if cost < costs[0] else "worse"})")
            print(f"{len([c for c in costs if c < costs[0]])} better costs found. best: {min(costs):.2f} ({100-(min(costs)/costs[0])*100:.2f}% improvement)")
            #print(f"{len([c for c in costs if c > costs[0]])} worse costs found. worst: {max(costs):.2f}")
            #print(f"{len([c for c in costs if c == costs[0]])} equal costs found.")
            print("\n")
        return cost

    def handle(self, *args, **options):
        RangeLocateKnobs()

        locator = Locator.load()
        scans: list[tuple[int, list[LocateWifiPeerSchema]]] = []
        correct_xyz = []
        costs = []
        for measurement in cast(Iterable[BeaconMeasurement], BeaconMeasurement.objects.select_related("space",
                                                                                                      "space__level")):
            for one_scan in measurement.data.wifi:
                scan_data = locator.convert_raw_scan_data(one_scan)
                result = locator.raw_locate_range(scan_data, debug=False)
                if result is None:
                    continue
                scans.append((measurement.space_id, one_scan))
                correct_xyz.append(measurement.correct_xyz)
        print(len(scans), "scans total to work with")

        correct_xyz = np.array(correct_xyz)

        knobs = RangeLocateKnobs()

        default_values = tuple(field.default for field in fields(knobs))

        from_i = 0  # 0
        to_i = 12  # len(default_values)

        if False:
            results = basinhopping(
                func=self.cost_func,
                minimizer_kwargs=dict(
                args=(scans, correct_xyz),
                bounds=RangeLocateKnobs.LIMITS,
                ),
                x0=tuple(getattr(knobs, field.name) for field in fields(knobs)),
            )
        elif False:
            results = minimize(
                fun=self.cost_func,
                args=(scans, correct_xyz),
                method="Nelder-Mead",
                # jac="3-point",
                # loss="linear",
                bounds=RangeLocateKnobs.LIMITS,
                # x_scale=10,
                x0=tuple(getattr(knobs, field.name) for field in fields(knobs)),
            )
        elif True:
            results = differential_evolution(
                func=self.cost_func,
                args=(scans, correct_xyz, costs, default_values, from_i, to_i),
                bounds=RangeLocateKnobs.LIMITS[from_i:to_i],
                x0=np.array(default_values[from_i:to_i]),
                polish=False,
                workers=-1,
            )


        print(RangeLocateKnobs(*results.x))
