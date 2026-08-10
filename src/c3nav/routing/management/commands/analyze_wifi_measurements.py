import json
from itertools import repeat
from operator import itemgetter
from typing import cast, Iterable

import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand
import matplotlib.pyplot as plt
from shapely import distance

from c3nav.mapdata.models.geometry.space import RangingBeacon, BeaconMeasurement
from c3nav.mapdata.utils.geometry import unwrap_geom
from c3nav.routing.locator import Locator, TypedIdentifier
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

        all_xyz = set(tuple(int(i) for i in line) for line in beacons_xyz.values())
        all_xyz_np = np.array(tuple(all_xyz))

        space_distance_by_rrsi = []

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

                strongest_space = beacons[strongest_beacon_id]
                if beacons[strongest_beacon_id].space != measurement.space:
                    print(f"strongest beacon at {strongest_value.rssi} dB"
                          f" - beacon space: {beacons[strongest_beacon_id].space.title}"
                          f" - correct space: {measurement.space.title}")
                    space_distance = (beacons[strongest_beacon_id].space != measurement.space)
                else:
                    space_distane = distance(unwrap_geom(beacons[strongest_beacon_id].space.geometry), unwrap_geom(measurement.geometry))

                valid = correct_altitude <= closest_altitude or correct_altitude <= strongest_altitude
                #print(f"#{measurement.pk}/{j}:", "valid" if valid else "invalid")

                visible_ap_ranks.extend(collect_ranks)

                correct_altitudes.append(correct_altitude)
                closest_altitudes.append(closest_altitude)
                strongest_altitudes.append(strongest_altitude)
                altitudes.append([beacons_xyz[beacon_id][2] for scan_value, beacon_id in scan_values])
                labels.append("" if has else f"#{measurement.pk}")



                has = True

        visible_ap_ranks = np.array(visible_ap_ranks)
        fig, ax = plt.subplots()

        if True:
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

        if False:
            ax.scatter(
                visible_ap_ranks[:, 0],
                visible_ap_ranks[:, 1],
                np.clip(visible_ap_ranks[:, 2]*-1+100, 10, None),
                c="red",
                alpha=0.3,
            )
            ax.set_yscale('log')
            ax.set_xticks(list(range(len(closest_altitudes))))
            ax.set_xticklabels(labels)

        plt.show()

