import json
from itertools import repeat
from operator import itemgetter
from typing import cast, Iterable

import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand
import matplotlib.pyplot as plt

from c3nav.mapdata.models.geometry.space import RangingBeacon, BeaconMeasurement
from c3nav.routing.locator import Locator, TypedIdentifier
from c3nav.routing.schemas import BeaconMeasurementDataSchema


class Command(BaseCommand):
    help = 'analyse distances between beacons'

    def handle(self, *args, **options):
        locator = Locator.load()
        identifier_to_beacon: dict[TypedIdentifier, int] = {}
        beacons: dict[int, RangingBeacon] = {}
        beacons_xyz: dict[int, np.typing.NDArray] = {}
        beacons_offsets: dict[int, list[float]] = {}
        measurements: list[tuple[float, ...]] = []
        colors: list[tuple[int, int, int]] = []
        for beacon in RangingBeacon.objects.select_related("space"):
            beacons[beacon.pk] = beacon
            beacons_xyz[beacon.pk] = np.array(locator.get_beacon_xyz(beacon))
            beacons_offsets[beacon.pk] = []
            identifiers = locator.get_beacon_identifiers(beacon)
            identifier_to_beacon.update(dict(zip(identifiers, repeat(beacon.pk))))

        inaccuracies = {}
        for measurement in cast(Iterable[BeaconMeasurement], BeaconMeasurement.objects.select_related("space")):
            measurement_xyz = np.array(measurement.correct_xyz)
            for scan in measurement.data.wifi:
                scan_values = []
                for scan_value in scan:
                    if scan_value.distance is None or scan_value.distance < 0:
                        continue
                    try:
                        beacon_id = next(iter(filter(
                            None,
                            (identifier_to_beacon.get(id_) for id_ in locator.get_scan_value_identifiers(scan_value))
                        )))
                    except StopIteration:
                        continue
                    scan_values.append((scan_value, beacon_id))

                if not scan_values:
                    continue

                rssis = [scan_value.rssi for scan_value, beacon_id in scan_values]
                distances = [scan_value.distance for scan_value, beacon_id in scan_values]
                max_rssi = max(rssis)
                min_distance = min(distances)
                yes = False
                for scan_value, beacon_id in scan_values:
                    if scan_value.distance is None or scan_value.distance < 0:
                        continue
                    try:
                        beacon_id = next(iter(filter(
                            None,
                            (identifier_to_beacon.get(id_) for id_ in locator.get_scan_value_identifiers(scan_value))
                        )))
                    except StopIteration:
                        continue
                    beacon = beacons[beacon_id]
                    scan_distance = max(0, scan_value.distance)
                    beacon_xyz = beacons_xyz[beacon_id]
                    correct_distance_3d = float(np.linalg.norm(measurement_xyz - beacon_xyz)/100)
                    correct_distance_2d = float(np.linalg.norm(measurement_xyz[:2] - beacon_xyz[:2]) / 100)
                    correct_distance_z = float(abs(measurement_xyz[2]-beacon_xyz[2]) / 100)
                    beacons_offsets[beacon_id].append(scan_distance-correct_distance_3d)
                    inaccuracy = scan_distance-correct_distance_3d
                    inaccuracy_percent = scan_distance / correct_distance_3d * 100
                    inaccuracies.setdefault(beacon_id, []).append(inaccuracy)
                    measurements.append((
                        correct_distance_3d,
                        scan_distance,
                        50 - min(correct_distance_z*10, 50) + 10,
                        (scan_value.distance_sd or 0),
                        scan_value.rssi * -1,
                        abs(correct_distance_z),
                        inaccuracy,
                        inaccuracy_percent,
                        (scan_value.distance_sd or 0)*scan_distance,
                        (scan_value.rssi - max_rssi) * -1,
                        (scan_value.distance - min_distance),
                    ))
                    if scan_value.rssi == max_rssi:
                        off = abs(measurement_xyz[2] - beacon_xyz[2])
                        #if off > 400 and len(scan_values) >= 3:
                        #    print("doent work:", off/100, "#", measurement.pk, beacon_xyz)
                    if scan_value.distance == min_distance:
                        off = abs(measurement_xyz[2] - beacon_xyz[2])
                        if off > 400 and len(scan_values) >= 3:
                            print("doent work:", off/100, "#", measurement.pk, beacon_xyz)
                        yes = True
                    colors.append(
                        (0, 0.6, 0) if beacon.space_id == measurement.space_id
                        else ((0.8, 0.8, 0) if beacon.space.level_id == measurement.space.level_id else (1, 0, 0))
                    )
                if not yes:
                    raise ValueError

        inaccuracies = dict(sorted(
            [(beacon_id, (sum(abs(i) for i in thelist)/len(thelist), thelist)) for beacon_id, thelist in inaccuracies.items()],
            key=lambda a: a[1][0], reverse=True,
        ))
        for beacon_id, (avg, thelist) in inaccuracies.items():
            print(f"beacon #{beacon_id}: avg off by: {avg:.1f}m - {[round(i) for i in thelist]}")

        print("Offsets (positive measured distance is bigger than actual distance)")
        for beacon_id, offsets in beacons_offsets.items():
            beacon = beacons[beacon_id]
            if offsets:
                min_ = min(offsets)
                max_ = max(offsets)
                print(f"RangingBeacon #{beacon_id} - {f"{beacon.space.title}: ".ljust(35, ".")} "
                      f"range={f"{max_-min_:.2f}".rjust(6)}m "
                      f"min={f"{min_:.2f}".rjust(6)}m max={f"{max_:.2f}".rjust(6)}m")
            else:
                print(f"RangingBeacon #{beacon_id} - {f"{beacon.space.title}: ".ljust(35, ".")} never seen")

        measurements: np.typing.NDArray = np.array(measurements)
        colors: np.typing.NDArray = np.array(colors)

        if True:
            #x_axis_i, x_axis_label = 0, "correct distance xyz (m)"
            x_axis_i, x_axis_label = 1, "measured distance (m)"
            #x_axis_i, x_axis_label = 3, "measured standard deviation (mm)"
            #x_axis_i, x_axis_label = 4, "rssi * -1"  # rssi
            #x_axis_i, x_axis_label = 5, "correct distance z (m)"
            x_axis_i, x_axis_label = 9, "(rssi - best_rssi) × -1"
            x_axis_i, x_axis_label = 10, "measaured distance - closest measured distance (m)"

            #y_axis_i, y_axis_label, is_log = 1, "measured distance (m)", False
            #y_axis_i, y_axis_label, is_log = 3, "measured standard deviation (mm)", True
            #y_axis_i, y_axis_label, is_log = 0, "correct distance (m)", False
            y_axis_i, y_axis_label, is_log = 5, "correct distance z (m)", False
            #y_axis_i, y_axis_label, is_log = 6, "measurement inaccuracy (m, lower means too short)", False
            #y_axis_i, y_axis_label, is_log = 7, "measurement inaccuracy (%)", False
            #y_axis_i, y_axis_label, is_log = 8, "measured distance × standard deviation", True

            x = measurements[:, x_axis_i]
            y = measurements[:, y_axis_i]
            print(x.shape, y.shape, colors.shape)
            A = np.vstack([x, np.ones(len(x))]).T
            alpha = np.dot((np.dot(np.linalg.inv(np.dot(A.T, A)), A.T)), y)

            fig, ax = plt.subplots()
            ax.scatter(x, y, np.abs(measurements[:, 6])*3+10, colors, alpha=0.3)
            ax.set_xlabel(x_axis_label, fontsize=15)
            ax.set_ylabel(y_axis_label, fontsize=15)
            ax.set_title('Accuracy of WiFi beacon measurements')
            if is_log:
                ax.set_xscale('log')
                ax.set_yscale('log')
                #ax.plot([1, 120], [1, 120], linestyle="dotted", linewidth=1.5, color='gray')
                #ax.plot([1, 120], [6, 125], linestyle="dotted", linewidth=1.5, color='gray')
                #ax.plot([1, 120], [11, 130], linestyle="dotted", linewidth=1.5, color='gray')
                #ax.plot([1, 120], [16, 135], linestyle="dotted", linewidth=1.5, color='gray')
                #ax.plot([1, 120], [21, 130], linestyle="dotted", linewidth=1.5, color='gray')
                # ax.plot([1, 120], [26, 135], linestyle="dotted", linewidth=1.5, color='gray')
                #ax.plot([1, 120], [31, 130], linestyle="dotted", linewidth=1.5, color='gray')
                # ax.plot([1, 120], [36, 135], linestyle="dotted", linewidth=1.5, color='gray')
                #ax.plot([1, 120], [41, 130], linestyle="dotted", linewidth=1.5, color='gray')
                # ax.plot([1, 120], [46, 135], linestyle="dotted", linewidth=1.5, color='gray')
                #ax.plot([5, 120], [3, 118], linestyle="dotted", linewidth=1.5, color='gray')
                #ax.plot([5, 120], [1, 116], linestyle="dotted", linewidth=1.5, color='gray')
            else:
                ax.plot([0, 120], [0, 0], linestyle="dotted", linewidth=1.5, color='gray')
                ax.plot([0, 120], [0, 120], linestyle="dotted", linewidth=1.5, color='gray')

            #plt.plot(x, alpha[0] * x + alpha[1], linestyle="dotted", linewidth=1.5, color='red')
            parabola_scale = 0.08
            parabola_xoff = 45
            parabola_yoff = 5
            ax.plot(
                tuple(range(1, 100)),
                tuple((i-parabola_xoff)**2*parabola_scale+parabola_yoff for i in range(1, 100)),
                linestyle="dashed", linewidth=1.5, color='gray'
            )
            ax.grid(True)
            ax.set_xlim(measurements[:, x_axis_i].min(axis=0), measurements[:, x_axis_i].max(axis=0))
            ax.set_ylim(measurements[:, y_axis_i].min(axis=0), measurements[:, y_axis_i].max(axis=0))
            fig.tight_layout()
            plt.show()

        if False:
            fig, ax = plt.subplots()
            ids, offsets = zip(*((f"#{i}", off) for i, off in beacons_offsets.items() if off))
            ax.boxplot(offsets)
            #ax.set_xlabel(r'actual distance', fontsize=15)
            #ax.set_ylabel(r'measured distance', fontsize=15)
            ax.set_xticklabels(ids)
            ax.set_title('Accuracy of WiFi beacon measurements, per AP')
            fig.tight_layout()
            plt.show()


