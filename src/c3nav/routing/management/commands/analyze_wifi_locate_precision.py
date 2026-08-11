import math
import time
from itertools import chain
from typing import cast, Iterable

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from django.core.management.base import BaseCommand
from shapely import Point
from shapely.affinity import scale
from shapely.ops import unary_union
from shapely.plotting import plot_polygon
from c3nav.mapdata.models.geometry.space import RangingBeacon, BeaconMeasurement
from c3nav.mapdata.utils.geometry import unwrap_geom
from c3nav.routing.locator import Locator


class Command(BaseCommand):
    help = 'analyse range-based positioning precision for beacon measurements'

    def handle(self, *args, **options):
        locator = Locator.load()

        levels = {}

        level_locations: dict[int, list[tuple[int, int, int, int, int, int]]] = {}
        level_ap_lines: dict[int, list[tuple[tuple[int, int], tuple[int, int]]]] = {}
        level_correct_lines: dict[int, list[tuple[tuple[int, int], tuple[int, int]]]] = {}
        level_beacons: dict[int, list[tuple[int, int, int]]] = {}
        accuracies: list[tuple[int, float, float, float, bool, bool]] = []

        from c3nav.routing.router import Router
        router = Router.load()

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
        totaltime = 0
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

            for j, scan in enumerate(measurement.data.wifi):
                start = time.time()
                scan_data = locator.convert_raw_scan_data(scan)
                result = locator.raw_locate_range(scan_data, debug=False, )
                totaltime += time.time()-start
                if result is None:
                    continue

                peer_xyzs = set(locator.peers[peer_id].xyz for peer_id in scan_data)
                best_peer_xyzs = [
                    xyz for xyz, rssi in
                    sorted(((locator.peers[peer_id].xyz, value.rssi) for peer_id, value in scan_data.items()),
                           key=lambda a: a[1], reverse=True)
                ]
                accuracy = np.linalg.norm(np.array(result.xyz)-np.array(measurement.correct_xyz))
                accuracy_2d = np.linalg.norm(np.array(result.xyz)[:2] - np.array(measurement.correct_xyz)[:2])
                accuracy_z = max(0.01, abs(result.xyz[2] - measurement.correct_xyz[2]))
                level_locations[level_id].append((*result.xyz, accuracy, len(peer_xyzs)))

                located_level_id = router.level_id_for_xyz(
                    # -1.3m cause we assume people to be above ground
                    (result.xyz[0]/100, result.xyz[1]/100, result.xyz[2]/100 - (1.3 if result.dimensions == 3 else 0)),
                    restrictions=None, # yeah this is right
                )
                point = Point(result.xyz[0]/100, result.xyz[1]/100)
                if True:
                    new_level, new_point = locator.move_into_space(
                        router=router, level=router.levels[located_level_id], point=point,
                        restrictions=(), max_space_distance=20,
                    )
                    located_level_id = new_level.id
                    point = new_point
                if located_level_id == measurement.space.level_id:
                    level_correct = True
                    located_space_id = router.space_for_point(located_level_id, point, restrictions=())
                    space_correct = located_space_id.pk == measurement.space_id
                    if accuracy_2d > 1500:
                        print(f"measurement #{measurement.pk}/{j} has accuracy {accuracy_2d/100:.2f}m")
                else:
                    level_correct = router.levels[located_level_id].on_top_of_id == measurement.space.level_id
                    space_correct = False

                highlight = level_correct and accuracy_2d > 2000
                highlight = not space_correct or accuracy_2d > 500

                accuracies.append((len(peer_xyzs), accuracy, accuracy_2d, accuracy_z, level_correct, space_correct))

                if highlight:
                    level_correct_lines[level_id].append((
                        *zip(result.xyz[:2], measurement.correct_xyz[:2]),
                        ((1, 0, 0) if result.xyz[2] < measurement.correct_xyz[2] else (0, 0, 1))
                         if located_level_id != measurement.space.level_id else (0.5, 0.5, 0.5),
                    ))

                    for peer_xyz in best_peer_xyzs[:1]:  # peer_xyzs:
                        #level_ap_lines[level_id].append(tuple(zip(result.xyz[:2], peer_xyz[:2])))
                        level_ap_lines[level_id].append(tuple(zip(measurement.correct_xyz[:2], peer_xyz[:2])))

        avg_time = totaltime/len(accuracies)

        num_correct_levels = 0
        num_correct_spaces = 0
        accuracies_2d_correct_level = []
        accuracies_2d_wrong_level = []
        for num_peers, accuracy_3d, accuracy_2d, accuracy_z, correct_level, correct_space in accuracies:
            if correct_level:
                accuracies_2d_correct_level.append(accuracy_2d)
                num_correct_levels += 1
                if correct_space:
                    num_correct_spaces += 1
            else:
                accuracies_2d_wrong_level.append(accuracy_2d)

        accuracies_2d_correct_level.sort()
        accuracies_2d_wrong_level.sort()

        print(f"{num_correct_levels/len(accuracies)*100:.1f}% of all measurements locate to the correct level, of which...")
        print(f" - {num_correct_spaces/num_correct_levels*100:.1f}% locate to the correct space")
        last_target = 0
        for i, accuracy_2d in enumerate(accuracies_2d_correct_level, start=1):
            current_target = int(i/num_correct_levels*10)
            if last_target != current_target:
                last_target = current_target
                print(f" - {current_target*10}% are 2D accurate <= {accuracy_2d/100:.1f} m")
        print(f"for measurements that do not locate to the correct level...")
        last_target = 0
        for i, accuracy_2d in enumerate(accuracies_2d_wrong_level, start=1):
            current_target = int(i / (len(accuracies)-num_correct_levels) * 10)
            if last_target != current_target:
                last_target = current_target
                print(f" - {current_target*10}% are 2D accurate <= {accuracy_2d/100:.1f} m")

        print(f"AVG TIME: {avg_time*1000:.2f}ms")

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
                ax.arrow(x[1], y[1], x[0]-x[1], y[0]-y[1], linestyle="solid", linewidth=1, color=color)
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
            x=accuracies[:, 0]-0.3,
            y=accuracies[:, 1] / 100,
            c="red",
            s=30,
            alpha=0.3,
        )
        ax.scatter(
            x=accuracies[:, 0]+0.3,
            y=np.abs(accuracies[:, 3]) / 100,
            c="blue",
            s=30,
            alpha=0.3,
        )
        ax.set_title("Inaccuracy")
        ax.set_xlabel("Number of visible Ranging Beacons", fontsize=15)
        ax.set_ylabel("Inaccuracy (m)", fontsize=15)
        ax.set_yscale('log')
        plt.subplots_adjust(left=0.02, bottom=0.03, right=0.98, top=0.95, hspace=0.07, wspace=0.05)



        plt.show()

