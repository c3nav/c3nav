import json
from itertools import repeat, chain
from typing import cast, Iterable

import matplotlib
import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand
import matplotlib.pyplot as plt
from shapely.ops import unary_union
from shapely.plotting import plot_polygon
from shapely.affinity import scale

from c3nav.mapdata.models.geometry.space import RangingBeacon, BeaconMeasurement
from c3nav.mapdata.utils.geometry import unwrap_geom
from c3nav.routing.locator import Locator, TypedIdentifier
from c3nav.routing.schemas import BeaconMeasurementDataSchema


class Command(BaseCommand):
    help = 'analyse range-based positioning precision for beacon measurements'

    def handle(self, *args, **options):
        locator = Locator.load()

        levels = {}

        level_locations: dict[int, list[tuple[int, int, int, int, int, int]]] = {}
        level_ap_lines: dict[int, list[tuple[tuple[int, int], tuple[int, int]]]] = {}
        level_correct_lines: dict[int, list[tuple[tuple[int, int], tuple[int, int]]]] = {}
        level_beacons: dict[int, list[tuple[int, int, int]]] = {}
        accuracies: list[tuple[float, float]] = []

        arrangements = {
            1: (1, 1),
            2: (2, 1),
            3: (2, 2),
            4: (2, 2),
            5: (3, 2),
            6: (3, 2),
            7: (3, 3),
            8: (3, 3),
            9: (3, 3),
        }

        locator = Locator.load()
        for measurement in cast(Iterable[BeaconMeasurement], BeaconMeasurement.objects.select_related("space",
                                                                                                      "space__level")):
            level_id = measurement.space.level_id
            if level_id not in levels:
                levels[level_id] = measurement.space.level
                level_locations[level_id] = []
                level_correct_lines[level_id] = []
                level_ap_lines[level_id] = []
                level_beacons[level_id] = []

            if measurement.space.level_id not in levels:
                levels[measurement.space.level_id] = measurement.space.level

            for scan in measurement.data.wifi:
                scan_data = locator.convert_raw_scan_data(scan)
                result = locator.raw_locate_range(scan_data, debug=False)
                if result is None:
                    continue

                peer_xyzs = set(locator.peers[peer_id].xyz for peer_id in scan_data)
                accuracy = np.linalg.norm(np.array(result.xyz)-np.array(measurement.correct_xyz))
                level_locations[level_id].append((*result.xyz, accuracy, len(peer_xyzs)))
                accuracies.append((len(peer_xyzs), accuracy))

                level_correct_lines[level_id].append((*zip(result.xyz[:2], measurement.correct_xyz[:2]), result.xyz[2]-measurement.correct_xyz[2]))
                for peer_xyz in peer_xyzs:
                    level_ap_lines[level_id].append(tuple(zip(result.xyz[:2], peer_xyz[:2])))

        allxyz = np.array(tuple(chain.from_iterable(level_locations.values())))
        minx = np.min(allxyz[:, 0])
        maxx = np.max(allxyz[:, 0])
        miny = np.min(allxyz[:, 1])
        maxy = np.max(allxyz[:, 1])

        for ranging_beacon in RangingBeacon.objects.select_related("space"):
            if ranging_beacon.space.level_id in levels:
                level_beacons[ranging_beacon.space.level_id].append(locator.get_beacon_xyz(ranging_beacon))

        cols, rows = arrangements[len(levels)+1]
        fig, all_ax = plt.subplots(rows, cols)
        cmap_accuracy = matplotlib.colors.LinearSegmentedColormap.from_list("", ["lime", "green", "yellow", "red", "magenta", "darkviolet"])
        norm_accuracy = matplotlib.colors.Normalize(0*100, 25*100)
        cmap_altitude = matplotlib.colors.LinearSegmentedColormap.from_list("", ["blue", "gray", "gray", "gray", "red"])
        for i, (level_id, level) in enumerate(sorted(levels.items(), key=lambda a: a[1].base_altitude)):
            buildings = unary_union(tuple(unwrap_geom(building.geometry) for building in level.buildings.all()))
            walkable = unary_union((
                *(unwrap_geom(door.geometry) for door in level.doors.all()),
                *(
                    (
                        unwrap_geom(space.geometry).difference(buildings)
                        if space.outside
                        else unwrap_geom(space.geometry)
                    ).difference(unary_union(tuple(unwrap_geom(column.geometry) for column in space.columns.all())))
                    for space in level.spaces.prefetch_related("columns")
                 ),
            ))
            level.spaces.prefetch_related("columns")
            locations = np.array(level_locations[level_id])
            beacons = np.array(level_beacons[level_id])
            ax = all_ax[i // cols, i % cols]
            plot_polygon(scale(buildings, 100, 100, origin=(0, 0)), ax=ax, facecolor=(0.8, 0.8, 0.8, 1), add_points=False, linewidth=0, )
            plot_polygon(scale(walkable, 100, 100, origin=(0, 0)), ax=ax, facecolor=(0.95, 0.95, 0.95, 1), add_points=False, linewidth=0)
            ax.scatter(
                x=beacons[:, 0],
                y=beacons[:, 1],
                s=7,
                color=(0, 0, 0),
                alpha=0.3
            )
            for x, y in level_ap_lines[level_id]:
                ax.plot(x, y, linestyle="dotted", linewidth=1, color=(0.7, 0.7, 0.7), alpha=0.5)
            for x, y, color in level_correct_lines[level_id]:
                print(color, color/100, color/100/10+0.5)
                ax.arrow(x[1], y[1], x[0]-x[1], y[0]-y[1], linestyle="solid", linewidth=1, color=cmap_altitude(max(0, min(1, color/100/10+0.5))))  #
            ax.scatter(
                x=locations[:, 0],
                y=locations[:, 1],
                c=locations[:, 3],
                s=np.clip((locations[:, 4]-2)*5, 5, 100),
                cmap=cmap_accuracy,
                norm=norm_accuracy,
                alpha=0.3,
            )
            ax.set_title(str(level.title))
            ax.set_xlim(minx, maxx)
            ax.set_ylim(miny, maxy)
            ax.set_xticks([])
            ax.set_yticks([])
        #fig.tight_layout()

        ax = all_ax[len(levels) // cols, len(levels) % cols]
        accuracies = np.array(accuracies)
        ax.scatter(
            x=accuracies[:, 0],
            y=accuracies[:, 1]/100,
            c="red",
            s=30,
            alpha=0.5,
        )
        ax.set_title("Inaccuracy")
        ax.set_xlabel("Number of visible Ranging Beacons", fontsize=15)
        ax.set_yscale('log')
        ax.set_ylabel("Inaccuracy (m)", fontsize=15)

        plt.subplots_adjust(left=0.02, bottom=0.03, right=0.98, top=0.95, hspace=0.07, wspace=0.05)



        plt.show()

