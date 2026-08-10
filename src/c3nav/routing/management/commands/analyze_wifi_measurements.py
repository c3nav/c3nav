import json
import math
from itertools import repeat
from operator import itemgetter, attrgetter
from typing import cast, Iterable, Counter

import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand
import matplotlib.pyplot as plt
from shapely import distance

from c3nav.mapdata.models.geometry.space import RangingBeacon, BeaconMeasurement
from c3nav.mapdata.utils.geometry import unwrap_geom
from c3nav.routing.locator import Locator, TypedIdentifier
from c3nav.routing.router import Router
from c3nav.routing.schemas import BeaconMeasurementDataSchema


class Command(BaseCommand):
    help = 'analyse wifi measurements'

    def handle(self, *args, **options):
        locator = Locator.load()
        identifier_to_beacon: dict[TypedIdentifier, int] = {}
        beacons: dict[int, RangingBeacon] = {}
        beacons_xyz: dict[int, np.typing.NDArray] = {}
        beacons_offsets: dict[int, list[float]] = {}
        for beacon in RangingBeacon.objects.select_related("space"):
            beacons[beacon.pk] = beacon
            beacons_xyz[beacon.pk] = np.array(locator.get_beacon_xyz(beacon))
            beacons_offsets[beacon.pk] = []
            identifiers = locator.get_beacon_identifiers(beacon)
            identifier_to_beacon.update(dict(zip(identifiers, repeat(beacon.pk))))

        inaccuracies = {}

        altitudes = []
        labels = []
        closest_altitudes = []
        strongest_altitudes = []
        correct_altitudes = []
        visible_ap_ranks = []
        average_rssis = []
        space_distances = []

        all_xyz = set(tuple(int(i) for i in line) for line in beacons_xyz.values())
        all_xyz_np = np.array(tuple(all_xyz))

        space_distance_by_rrsi = []

        num_kept_wrong = 0
        num_fixed = 0
        num_broken = 0

        for i, measurement in enumerate(cast(Iterable[BeaconMeasurement], BeaconMeasurement.objects.select_related("space"))):
            has = False
            if i > 1500:
                break
            measurement_xyz = np.array(measurement.correct_xyz)
            distances = np.linalg.norm(all_xyz_np-measurement_xyz, axis=1)

            known_peer_xyz_by_closeness = {tuple(int(j) for j in line): i for i, line in enumerate(all_xyz_np[np.argsort(distances), :])}

            for j, scan in enumerate(measurement.data.wifi):
                scan_values = []
                collect_ranks = []
                for scan_value in scan:
                    if scan_value.distance is None:
                        continue
                    try:
                        beacon_id = next(iter(filter(
                            None,
                            (identifier_to_beacon.get(id_) for id_ in locator.get_scan_value_identifiers(scan_value))
                        )))
                    except StopIteration:
                        continue

                    scan_values.append((scan_value, beacon_id))
                    rank = known_peer_xyz_by_closeness[tuple(int(i) for i in beacons_xyz[beacon_id])]
                    collect_ranks.append((len(visible_ap_ranks), rank, scan_value.distance))


                if not scan_values:
                    continue

                correct_altitude = measurement_xyz[2]
                closest_values = sorted(scan_values, key=lambda a: a[0].distance)
                strongest_values = sorted(scan_values, key=lambda a: a[0].rssi, reverse=True)
                closest_value, closest_beacon_id = closest_values[0]
                strongest_value, strongest_beacon_id = strongest_values[0]
                closest_altitude = beacons_xyz[closest_beacon_id][2]
                strongest_altitude = beacons_xyz[strongest_beacon_id][2]

                acceptable_values = [(value, beacon_id) for value, beacon_id in strongest_values
                                     if value.rssi+5 >= strongest_value.rssi]
                all_spaces = [beacons[beacon_id].space_id for value, beacon_id in strongest_values]
                possible_spaces = [beacons[beacon_id].space_id for value, beacon_id in acceptable_values]

                main_space_id = possible_spaces[0]

                router = Router.load()

                spaces_on_top = {
                    58: [21, 28, 36],
                    21: [28, 36],
                    28: [36],
                    46: [45, 44],
                    45: [44],
                }
                spaces_below = {
                    36: [28, 21, 58],
                    28: [21, 58],
                    21: [58],
                    44: [45, 46],
                    45: [46],
                }

                if main_space_id in spaces_on_top or main_space_id in spaces_below:
                    connected = {main_space_id, *spaces_on_top.get(main_space_id, ()), *spaces_below.get(main_space_id, ())}
                    possible_says_us = [sid for sid in all_spaces if sid in connected]
                    for i in range(2, len(possible_says_us)+1):
                        sid, num = Counter(possible_says_us[:i]).most_common(1)[0]
                        if num == 2:
                            new_space_id = sid
                            break
                    else:
                        new_space_id = None

                    if main_space_id != measurement.space_id:
                        print("WAS WRONG:", router.spaces[main_space_id].title, "should be:", measurement.space.title)
                        print("measurement:", tuple(float(i)/100 for i in measurement.correct_xyz),
                              "beacon:", tuple(float(i)/100 for i in beacons_xyz[strongest_beacon_id]))
                        print(all_spaces)
                        if new_space_id is None:
                            print("- no change found")
                            num_kept_wrong += 1
                        elif new_space_id == main_space_id:
                            print("- kept wrong")
                            num_kept_wrong += 1
                        elif new_space_id == measurement.space_id:
                            print("- fixed")
                            num_fixed += 1
                        else:
                            print("- miscorrected:", router.spaces[new_space_id].title)
                            num_kept_wrong += 1
                    else:
                        print("WAS RIGHT:", measurement.space.title)
                        if new_space_id is None:
                            print("- kept")
                        elif new_space_id == main_space_id:
                            print("- confirmed")
                        else:
                            print(all_spaces)
                            print("- miscorrected:", router.spaces[new_space_id].title)
                            num_broken += 1

                else:
                    if possible_spaces[0] != measurement.space_id:
                        print("???", possible_spaces, "should be:", measurement.space_id, measurement.space.title, "... looks like", router.spaces[possible_spaces[0]].title)
                strongest_space = beacons[strongest_beacon_id]

                if beacons[strongest_beacon_id].space != measurement.space and False:

                    print(f"strongest beacon at {strongest_value.rssi} dB"
                          f" - beacon space: {beacons[strongest_beacon_id].space.title}"
                          f" - correct space: {measurement.space.title}")
                    space_distance = distance(unwrap_geom(strongest_space.geometry), unwrap_geom(measurement.geometry))
                else:
                    space_distance = 0

                average_rssis.append(np.average([value.rssi for value, beacon_id in scan_values[:int(math.ceil(len(scan_values)/2))]]))
                space_distances.append(space_distance)

                valid = correct_altitude <= closest_altitude or correct_altitude <= strongest_altitude
                #print(f"#{measurement.pk}/{j}:", "valid" if valid else "invalid")

                visible_ap_ranks.extend(collect_ranks)

                correct_altitudes.append(correct_altitude)
                closest_altitudes.append(closest_altitude)
                strongest_altitudes.append(strongest_altitude)
                altitudes.append([beacons_xyz[beacon_id][2] for scan_value, beacon_id in scan_values])
                labels.append("" if has else f"#{measurement.pk}")

                has = True

        print("kept_wrong:", num_kept_wrong, "fixed:", num_fixed, "broken:", num_broken)

        visible_ap_ranks = np.array(visible_ap_ranks)
        fig, ax = plt.subplots()

        if False:
            ax.boxplot(altitudes, tick_labels=labels)
            ax.set_xlabel("Measurement", fontsize=15)
            ax.set_ylabel("Altitude", fontsize=15)
            ax.set_title('Wifi Measurements Analysis')
            ax.scatter(range(len(correct_altitudes)), correct_altitudes, s=30, c="red", alpha=0.3)
            ax.scatter(range(len(closest_altitudes)), closest_altitudes, s=30, c="blue", alpha=0.3)
            ax.scatter(range(len(strongest_altitudes)), strongest_altitudes, s=30, c="green", alpha=0.3)
            #fig.tight_layout()
            ax.set_xticks(list(range(len(closest_altitudes))))
            plt.subplots_adjust(left=0.07, bottom=0.07, right=0.95, top=0.9)
            plt.show()

        if True:
            ax.scatter(
                np.array(average_rssis)*-1,
                np.array(space_distances),
                s=30,
                c="red",
                alpha=0.3,
            )
            #ax.set_yscale('log')
            #ax.set_xticks(list(range(len(closest_altitudes))))
            #ax.set_xticklabels(labels)

        plt.show()

