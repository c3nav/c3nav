import bisect
import operator
import pickle
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cached_property, reduce
from itertools import chain, combinations
from operator import itemgetter
from typing import Annotated, NamedTuple, Union
from typing import Optional, Self, Sequence, TypeAlias
from uuid import UUID

import numpy as np
from annotated_types import Lt
from django.conf import settings
from pydantic.types import NonNegativeInt
from pydantic_extra_types.mac_address import MacAddress
from shapely import Point
from shapely.ops import nearest_points

from c3nav.mapdata.models import MapUpdate, Space
from c3nav.mapdata.models.geometry.space import AutoBeaconMeasurement, BeaconMeasurement
from c3nav.mapdata.utils.cache.stats import increment_cache_key
from c3nav.mapdata.utils.locations import CustomLocation
from c3nav.mapdata.utils.placement import PointPlacementHelper
from c3nav.mesh.utils import get_nodes_and_ranging_beacons
from c3nav.routing.router import Router
from c3nav.routing.schemas import LocateWifiPeerSchema, BeaconMeasurementDataSchema, LocateIBeaconPeerSchema, \
    RangePeerSchema

try:
    from asgiref.local import Local as LocalContext
except ImportError:
    from threading import local as LocalContext


class PeerType(StrEnum):
    WIFI = "wifi"
    DECT = "dect"
    IBEACON = "ibeacon"


class TypedIdentifier(NamedTuple):
    peer_type: PeerType
    identifier: Union[
        MacAddress,
        str,
        tuple[UUID, Annotated[NonNegativeInt, Lt(2 ** 16)], Annotated[NonNegativeInt, Lt(2 ** 16)]]
    ]


@dataclass
class LocatorPeer:
    identifier: TypedIdentifier
    frequencies: list[int] = field(default_factory=list)
    xyz: Optional[tuple[int, int, int]] = None
    space_id: Optional[int] = None
    supports80211mc: bool = False
    seen_with: Counter = field(default_factory=Counter)
    seen_with_with: dict[int, Counter] = field(default_factory=lambda: defaultdict(Counter))

    @cached_property
    def suggestion(self) -> RangePeerSchema:
        return RangePeerSchema(
            bssid=self.identifier.identifier,
            frequencies=self.frequencies,
        )


@dataclass
class ScanDataValue:
    rssi: Optional[int] = None
    ibeacon_range: Optional[float] = None
    distance: Optional[float] = None
    distance_sd: Optional[float] = None

    @classmethod
    def average(cls, items: Sequence[Self]):
        rssi = [item.rssi for item in items if item.rssi]
        ibeacon_range = [item.ibeacon_range for item in items if item.ibeacon_range is not None]
        distance = [item.distance for item in items if item.distance is not None]
        distance_sd = [item.distance_sd for item in items if item.distance_sd is not None]  # pretty sure this is wrong
        return cls(
            rssi=(sum(rssi)//len(rssi)) if rssi else None,
            ibeacon_range=(sum(ibeacon_range) // len(ibeacon_range)) if ibeacon_range else None,
            distance=(sum(distance)/len(distance)) if distance else None,
            distance_sd=(sum(distance_sd) / len(distance_sd)) if distance_sd else None,
        )


ScanData: TypeAlias = dict[int, ScanDataValue]


@dataclass
class LocatorPoint:
    x: float
    y: float
    values: ScanData


class LocatorResult(NamedTuple):
    location: Optional[CustomLocation]
    suggested_peers: list[RangePeerSchema]
    precision: Optional[float] = None
    analysis: Optional[list[str]] = None


@dataclass
class Locator:
    peers: list[LocatorPeer] = field(default_factory=list)
    peer_lookup: dict[TypedIdentifier, int] = field(default_factory=dict)
    xyz: np.array = field(default_factory=(lambda: np.empty((0,))))
    spaces: dict[int, "LocatorSpace"] = field(default_factory=dict)
    placement_helper: Optional[PointPlacementHelper] = None
    peers_with_80211mc: frozenset[int] = field(default_factory=frozenset)
    initial_80211mc_peers: list[int] = field(default_factory=list)

    @cached_property
    def initial_suggested_peers(self) -> list[RangePeerSchema]:
        return [self.peers[peer_id].suggestion for peer_id in self.initial_80211mc_peers]

    @classmethod
    def rebuild(cls, update, router):
        locator = cls()
        locator._rebuild(router)
        pickle.dump(locator, open(cls.build_filename(update), 'wb'))
        return locator

    def _rebuild(self, router):
        calculated = get_nodes_and_ranging_beacons()

        # get ranging bssids first
        measurements = list(chain(AutoBeaconMeasurement.objects.order_by('-datetime'),
                                  BeaconMeasurement.objects.order_by('-pk')))
        ranging_bssids: set[str] = set()
        for m in measurements:
            for item in chain.from_iterable(m.data.wifi):
                if item.distance is not None:
                    ranging_bssids.add(item.bssid.lower())

        # go through beacons, create peers
        for beacon in calculated.beacons.values():
            identifiers = []
            for bssid in beacon.addresses:
                identifiers.append(TypedIdentifier(PeerType.WIFI, bssid.lower()))
            if beacon.ap_name:
                identifiers.append(TypedIdentifier(PeerType.WIFI, beacon.ap_name))
            if beacon.ibeacon_uuid and beacon.ibeacon_major is not None and beacon.ibeacon_minor is not None:
                identifiers.append(
                    TypedIdentifier(PeerType.IBEACON, (beacon.ibeacon_uuid, beacon.ibeacon_major, beacon.ibeacon_minor))
                )
            for identifier in identifiers:
                peer_id = self.get_peer_id(identifier, create=True)
                self.peers[peer_id].xyz = (
                    int(beacon.geometry.x * 100),
                    int(beacon.geometry.y * 100),
                    int((router.altitude_for_point(beacon.space_id, beacon.geometry) + float(beacon.altitude)) * 100),
                )
                if identifier.identifier in ranging_bssids:
                    self.peers[peer_id].supports80211mc = True
                self.peers[peer_id].space_id = beacon.space_id
        self.xyz = np.array(tuple(peer.xyz for peer in self.peers))

        peer_ids_80211mc = tuple(i for i, peer in enumerate(self.peers) if peer.supports80211mc)
        self.peers_with_80211mc = frozenset(peer_ids_80211mc)

        # write down frequencies based on latest data
        for m in measurements:
            for value in chain.from_iterable(reversed(m.data.wifi)):
                peer_id = self.peer_lookup.get(TypedIdentifier(PeerType.WIFI, value.bssid), None)
                if peer_id is not None and value.frequency not in self.peers[peer_id].frequencies:
                    self.peers[peer_id].frequencies.append(value.frequency)


        # count seen with
        range_peer_counter = Counter()
        for m in measurements:
            for scan in m.data.wifi:
                converted_scan = {peer_id: value for peer_id, value in self.convert_wifi_scan(scan).items()
                                  if peer_id in peer_ids_80211mc}
                if not converted_scan:
                    break

                peer_ids = sorted(converted_scan.keys())
                peer_ids_set = set(converted_scan.keys())
                range_peer_counter.update(peer_ids)
                for peer_id in peer_ids:
                    self.peers[peer_id].seen_with.update(peer_ids_set - {peer_id})
                for peer_id_0, peer_id_1 in combinations(peer_ids, 2):
                    self.peers[peer_id_0].seen_with_with[peer_id_1].update(peer_ids_set - {peer_id_0, peer_id_1})

        # find minimum peers
        minimum_peers_80211mc = set()
        remaining_well_seen: dict[int, set[int]] = {}
        for peer_id in peer_ids_80211mc:
            remaining_well_seen[peer_id] = set(self.peers[peer_id].seen_with.keys())

        while remaining_well_seen:
            best_peer_id, best_seen = max(remaining_well_seen.items(), key=lambda i: len(i[1]))
            remaining_well_seen.pop(best_peer_id, None)
            minimum_peers_80211mc.add(best_peer_id)
            for peer_id in best_seen:
                remaining_well_seen.pop(peer_id, None)
            remaining_well_seen = {
                peer_id: seen for peer_id, seen in (
                    (peer_id, seen - best_seen) for peer_id, seen in remaining_well_seen.items()
                ) if seen
            }

        self.initial_80211mc_peers = sorted(
            minimum_peers_80211mc, key=lambda peer_id: range_peer_counter[peer_id], reverse=True
        )

        for peer in self.peers:
            peer.seen_with_with = dict(peer.seen_with_with.items())

        for space in Space.objects.prefetch_related('beacon_measurements'):
            new_space = LocatorSpace.create(
                pk=space.pk,
                points=tuple(
                    LocatorPoint(
                        x=measurement.geometry.x,
                        y=measurement.geometry.y,
                        values=self.convert_scans(measurement.data, create_peers=True),
                    )
                    for measurement in space.beacon_measurements.all()
                )
            )
            if new_space.points:
                self.spaces[space.pk] = new_space

        self.placement_helper = PointPlacementHelper()

    def get_peer_id(self, identifier: TypedIdentifier, create=False) -> Optional[int]:
        peer_id = self.peer_lookup.get(identifier, None)
        if peer_id is None and create:
            peer = LocatorPeer(identifier=identifier)
            peer_id = len(self.peers)
            self.peer_lookup[identifier] = peer_id
            self.peers.append(peer)
        return peer_id

    def convert_wifi_scan(self, scan_data: list[LocateWifiPeerSchema], create_peers=False) -> ScanData:
        result = {}
        for scan_value in scan_data:
            if settings.WIFI_SSIDS and scan_value.ssid not in settings.WIFI_SSIDS:
                continue
            peer_ids = {
                self.get_peer_id(TypedIdentifier(PeerType.WIFI, scan_value.bssid.lower()), create=create_peers),
                self.get_peer_id(TypedIdentifier(PeerType.WIFI, scan_value.ap_name), create=create_peers),
            } - {None, ""}
            for peer_id in peer_ids:
                result[peer_id] = ScanDataValue(rssi=scan_value.rssi,
                                                distance=scan_value.distance,
                                                distance_sd=scan_value.distance_sd)
        return result

    def convert_ibeacon_scan(self, scan_data: list[LocateIBeaconPeerSchema], create_peers=False) -> ScanData:
        result = {}
        for scan_value in scan_data:
            peer_id = self.get_peer_id(
                TypedIdentifier(PeerType.IBEACON, (scan_value.uuid, scan_value.major, scan_value.minor)),
                create=create_peers
            )
            if peer_id is not None:
                result[peer_id] = ScanDataValue(ibeacon_range=scan_value.distance)
        return result

    def convert_scans(self, scans_data: BeaconMeasurementDataSchema, create_peers=False) -> ScanData:
        converted = []
        for scan in scans_data.wifi:
            converted.append(self.convert_wifi_scan(scan, create_peers=create_peers))

        for scan in scans_data.ibeacon:
            converted.append(self.convert_ibeacon_scan(scan, create_peers=create_peers))

        peer_ids = reduce(operator.or_, (frozenset(values.keys()) for values in converted), frozenset())
        return {
            peer_id: ScanDataValue.average(
                tuple(values[peer_id] for values in converted if peer_id in values)
            )
            for peer_id in peer_ids
        }

    @classmethod
    def build_filename(cls, update):
        return settings.CACHE_ROOT / MapUpdate.build_cache_key(*update) / 'locator.pickle'

    @classmethod
    def load_nocache(cls, update):
        return pickle.load(open(cls.build_filename(update), 'rb'))

    cached = LocalContext()

    class NoUpdate:
        pass

    @classmethod
    def load(cls):
        from c3nav.mapdata.models import MapUpdate
        update = MapUpdate.last_processed_update()
        if getattr(cls.cached, 'update', cls.NoUpdate) != update:
            cls.cached.update = update
            cls.cached.data = cls.load_nocache(update)
        return cls.cached.data

    def convert_raw_scan_data(self, raw_scan_data: list[LocateWifiPeerSchema]) -> ScanData:
        return self.convert_wifi_scan(raw_scan_data, create_peers=False)

    def get_xyz(self, identifier: TypedIdentifier) -> tuple[int, int, int] | None:
        i = self.get_peer_id(identifier)
        if i is None:
            return None
        return self.peers[i].xyz

    def get_all_nodes_xyz(self) -> dict[TypedIdentifier, tuple[int, int, int]]:
        return {
            peer.identifier: peer.xyz for peer in self.peers[:len(self.xyz)]
            if isinstance(peer.identifier, MacAddress)
        }

    def locate(self, raw_scan_data: list[LocateWifiPeerSchema], permissions=None,
               correct_xyz: Optional[tuple[int, int, int]] = None) -> LocatorResult:
        # todo: support for ibeacons
        scan_data = self.convert_raw_scan_data(raw_scan_data)

        result = self.locate_range(scan_data, permissions, correct_xyz=correct_xyz)
        if result.location is not None:
            increment_cache_key('apistats__locatemethod__range')
            return result

        suggestions = result.suggested_peers

        if not scan_data:
            return LocatorResult(location=None, suggested_peers=suggestions)

        result = self.locate_by_beacon_positions(scan_data, permissions)
        if result is not None:
            increment_cache_key('apistats__locatemethod__beaconpositions')
            return LocatorResult(location=result, suggested_peers=suggestions)

        result = self.locate_rssi(scan_data, permissions)
        if result is not None:
            increment_cache_key('apistats__locatemethod__rssi')
        return LocatorResult(location=result, suggested_peers=suggestions)

    def locate_by_beacon_positions(self, scan_data: ScanData, permissions=None) -> Optional[CustomLocation]:
        scan_data_we_can_use = sorted([
            (peer_id, value) for peer_id, value in scan_data.items()
            if self.peers[peer_id].space_id and -90 < value.rssi < -10
        ], key=lambda a: -a[1].rssi)

        if not scan_data_we_can_use:
            return None

        router = Router.load()
        restrictions = router.get_restrictions(permissions)

        # get visible spaces
        best_ap_id = max(scan_data_we_can_use, key=lambda item: item[1].rssi)[0]
        space_id = self.peers[best_ap_id].space_id
        space = router.spaces[space_id]

        already_got = set()
        selected_scan_data_in_the_same_room = []
        selected_scan_data_in_other_rooms = []
        for peer_id, value in scan_data_we_can_use:
            key = tuple(self.peers[peer_id].xyz)
            if key in already_got:
                continue
            already_got.add(key)
            if self.peers[peer_id].space_id == space_id:
                selected_scan_data_in_the_same_room.append((peer_id, value))
            else:
                if not selected_scan_data_in_other_rooms:
                    selected_scan_data_in_other_rooms.append((peer_id, value))
            if (len(selected_scan_data_in_the_same_room) + len(selected_scan_data_in_other_rooms)) == 4:
                break

        selected_scan_data = selected_scan_data_in_the_same_room + selected_scan_data_in_other_rooms

        the_sum = sum((value.rssi + 90) for peer_id, value in selected_scan_data)

        level = router.levels[space.level_id]
        if not the_sum:
            point = space.point
        else:
            x = 0
            y = 0
            # sure this can be better probably
            for peer_id, value in selected_scan_data:
                x += float(self.peers[peer_id].xyz[0]) * (value.rssi+90) / the_sum
                y += float(self.peers[peer_id].xyz[1]) * (value.rssi+90) / the_sum
            point = Point(x/100, y/100)

        # todo: add some kind of jitter
        try:
            point = nearest_points(space.geometry.buffer(-0.25), point)[0]
        except KeyError:
            point = nearest_points(space.geometry.buffer(0), point)[0]

        new_space, new_point = self.placement_helper.get_point_and_space(
            level_id=level.pk, point=point, restrictions=restrictions,
            max_space_distance=20,
        )

        if new_space is not None:
            level = router.levels[new_space.level_id]
        if level.on_top_of_id:
            level = router.levels[level.on_top_of_id]

        return CustomLocation(
            level=level,
            x=new_point.x,
            y=new_point.y,
            permissions=permissions,
            icon='my_location'
        )

    def locate_rssi(self, scan_data: ScanData, permissions=None) -> Optional[CustomLocation]:
        router = Router.load()
        restrictions = router.get_restrictions(permissions)

        # get visible spaces
        spaces = tuple(space for pk, space in self.spaces.items() if pk not in restrictions.spaces)

        # find best point
        best_peer_id = max(scan_data.items(), key=lambda v: v[1].rssi)[0]
        best_location = None
        best_score = float('inf')
        for space in spaces:
            point, score = space.get_best_point(scan_data, needed_peer_id=best_peer_id)
            if point is None:
                continue
            if score < best_score:
                location = CustomLocation(router.spaces[space.pk].level, point.x, point.y,
                                          permissions=permissions, icon='my_location')
                best_location = location
                best_score = score

        if best_location is not None:
            best_location.score = best_score

        if best_location is not None:
            return None

        return best_location

    @cached_property
    def least_squares_func(self):
        # this is effectively a lazy import to save memory… todo: do we need that?
        from scipy.optimize import minimize
        return minimize

    @cached_property
    def norm_func(self):
        # this is effectively a lazy import to save memory… todo: do we need that?
        from scipy.linalg import norm
        return norm

    def _deduplicate_peer_ids(self, peer_ids: tuple[int, ...]) -> tuple[int, ...]:
        had_xyz = set()
        result = []
        for peer_id in peer_ids:
            xyz = tuple(self.xyz[peer_id, :].flatten())
            if xyz in had_xyz:
                continue
            had_xyz.add(xyz)
            result.append(peer_id)
        return tuple(result)

    def locate_range(self, scan_data: ScanData, permissions=None, orig_addr=None,
                     correct_xyz: Optional[tuple[int, int, int]] = None) -> LocatorResult:
        peer_ids = self._deduplicate_peer_ids(
            tuple(i for i, item in scan_data.items() if i < len(self.xyz) and item.distance)
        )

        if not peer_ids:
            return LocatorResult(
                location=None,
                suggested_peers=self.initial_suggested_peers
            )

        if len(peer_ids) == 1:
            return LocatorResult(
                location=None,
                suggested_peers=(
                    [self.peers[pid].suggestion for pid, c in self.peers[peer_ids[0]].seen_with.most_common(20)]
                    or self.initial_suggested_peers
                )
            )

        if len(peer_ids) == 2:
            # todo: maybe we can at least give something?
            return LocatorResult(
                location=None,
                suggested_peers=(
                    [self.peers[pid].suggestion
                     for pid, c in self.peers[min(peer_ids)].seen_with_with.get(max(peer_ids), Counter()).most_common(20)]
                    or self.initial_suggested_peers
                ),
            )

        if len(peer_ids) == 3:
            if settings.DEBUG:
                print('2D trilateration')
            dimensions = 2
        else:
            if settings.DEBUG:
                print('3D trilateration')
            dimensions = 3

        relevant_xyz = self.xyz[peer_ids, :]

        # create 2d array with x, y, z, distance as rows
        np_ranges = np.hstack((
            relevant_xyz,
            np.array(tuple(float(scan_data[i].distance) for i in peer_ids)).reshape((-1, 1))*100,
        ))

        #print(np_ranges)

        measured_ranges = np_ranges[:, 3]
        #print('a', measured_ranges)
        # measured_ranges[measured_ranges<1] = 1
        #print('b', measured_ranges)

        if settings.DEBUG:
            print("relevant", relevant_xyz)
            print("measured_ranges", measured_ranges)

        # rating the guess by calculating the distances
        def diff_func(guess):
            result = self.norm_func(np_ranges[:, :dimensions] - guess[:dimensions], axis=1) - measured_ranges
            # print(result)
            return result
            # factors = self.norm_func(np_ranges[:, :dimensions] - guess[:dimensions], axis=1) / measured_ranges
            # return factors - np.mean(factors)

        def cost_func(guess):
            if settings.DEBUG:
                print("guess", guess)
            result = diff_func(guess) * -1
            if settings.DEBUG:
                print("diff", result)
            result[result < 0] = result[result < 0] * -2
            cost = np.sum(result ** 2)
            if settings.DEBUG:
                print("cost", result, cost)
            return cost

        # initial guess is the average of all beacons, with scale 1
        initial_guess = np.average(np_ranges, axis=0)

        #initial_guess = (76.96*100, 183.65*100, 1600)

        # here the magic happen
        bounds = tuple(zip(tuple(np.min(self.xyz[:, :2], axis=0) - np.array([200, 200, 100])[:2]),
                           tuple(np.max(self.xyz[:, :2], axis=0) + np.array([200, 200, 100])[:2])))

        if dimensions == 3:
            bounds += ((min(relevant_xyz[:, 2]), max(relevant_xyz[:, 2])),)
        if settings.DEBUG:
            print(bounds)
        results = self.least_squares_func(
            fun=cost_func,
            # jac="3-point",
            #loss="linear",
            bounds=bounds,
            #x_scale=10,
            x0=initial_guess[:dimensions],
        )

        # create result
        router = Router.load()
        restrictions = router.get_restrictions(permissions)

        result_distances = self.norm_func(np_ranges[:, :dimensions] - results.x, axis=1)/100
        precision = round(float(np.median(np.abs(diff_func(results.x))))/100*1.1, 2)

        result_pos = tuple(i/100 for i in results.x)
        if dimensions == 2:
            result_pos += (initial_guess[2]/100, )

        level = router.levels[router.level_id_for_xyz(
            # -1.3m cause we assume people to be above ground
            (result_pos[0], result_pos[1], result_pos[2] - 1.3),
            restrictions
        )]
        if level.on_top_of_id:
            level = router.levels[level.on_top_of_id]

        location = CustomLocation(
            level=level,
            x=result_pos[0],
            y=result_pos[1],
            permissions=permissions,
            icon='my_location'
        )
        location.z = result_pos[2]


        analysis = []
        if correct_xyz is not None:
            correct_distances = np.linalg.norm(self.xyz[peer_ids, :] - np.array(correct_xyz), axis=1)/100
            for peer_id, result_distance, correct_distance in zip(peer_ids, result_distances, correct_distances):
                peer = self.peers[peer_id]
                value = scan_data[peer_id]
                analysis.append(f"{tuple(round(float(i)/100, 2) for i in peer.xyz)}: "
                                f"{value.distance:.2f} m (sd: {value.distance_sd:.2f} m) - {value.rssi} dB")
                analysis.append(f"→ result: {round(float(result_distance), 2):.2f} m"
                                f" ({value.distance-result_distance:+.1f} m)"
                                f"→ correct: {correct_distance:.2f} m"
                                f" ({value.distance-correct_distance:+.1f} m)")

        if correct_xyz is not None:
            distance = float(np.linalg.norm(results.x - np.array(correct_xyz[:dimensions])))/100

            analysis.insert(0,
                            f"{tuple(round(float(i)/100, 2) for i in results.x)} → "
                            f"{tuple(round(float(i)/100, 2) for i in correct_xyz[:dimensions])} "
                            f"(off by {distance:.2f} m)")

        # get suggested peers
        remaining_peer_ids = tuple(self.peers_with_80211mc - set(peer_ids))
        print(remaining_peer_ids, self.xyz)
        distances = (
            np.linalg.norm(self.xyz[remaining_peer_ids, :] - np.array(tuple(int(i)*100 for i in result_pos)), axis=1)
        )
        suggested_ids = sorted(list(zip(remaining_peer_ids, distances)), key=itemgetter(1))
        index = bisect.bisect_left([dist for i, dist in suggested_ids], 50)
        suggestions = [
            self.peers[peer_id].suggestion
            for peer_id, distance in (suggested_ids[:10] if index < 10 else suggested_ids[:index])
        ]

        orig_xyz = None
        if settings.DEBUG:
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
                ("%.2f" % i) for i in tuple(self.norm_func(np_ranges[:, :dimensions] - result_pos[:dimensions], axis=1))
            ))
            if orig_xyz is not None:
                print("correct ranges:", ", ".join(
                    ("%.2f" % i)
                    for i in tuple(self.norm_func(np_ranges[:, :dimensions] - orig_xyz[:dimensions], axis=1))
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

            #def print_cost(title, pos):
            #    cost = cost_func(pos)
            #    print(title, ", ".join(
            #        ("%.2f" % i) for i in cost
            #    ), '=', np.sum(cost**2))
            #print_cost("cost:", result_pos)
            #if orig_xyz is not None:
            #    print_cost("cost of correct position:", orig_xyz)
            if dimensions > 2:
                print("height:", result_pos[2])
            # print("scale:", (factor or results.x[3]))

        increment_cache_key('apistats__locaterangepeers__%s' % len(peer_ids))

        return LocatorResult(
            location=location,
            suggested_peers=suggestions,
            analysis=analysis,
            precision=precision,
        )


no_signal = int(-90)**2


@dataclass
class LocatorSpace:
    pk: int
    points: list[LocatorPoint]
    peer_ids: frozenset[int]
    peer_lookup: dict[int, int]
    levels: np.array

    @classmethod
    def create(cls, pk: int, points: Sequence[LocatorPoint]):
        peer_set = reduce(operator.or_, (frozenset(point.values.keys()) for point in points), frozenset())
        peers = tuple(peer_set)
        peer_lookup = {peer_id: i for i, peer_id in enumerate(peers)}
        levels = np.full((len(points), len(peers)), fill_value=no_signal, dtype=np.int64)
        for i, point in enumerate(points):
            for peer_id, value in point.values.items():
                if value.rssi is None:
                    continue  # todo: ibeaconrange
                levels[i][peer_lookup[peer_id]] = int(value.rssi)**2

        return cls(
            pk=pk,
            points=list(points),
            peer_ids=peer_set,
            peer_lookup=peer_lookup,
            levels=levels,
        )

    def get_best_point(self, scan_values: ScanData,
                       needed_peer_id=None) -> tuple[LocatorPoint, float] | tuple[None, None]:
        # check if this space knows the needed peer id, otherwise no results here
        if needed_peer_id not in self.peer_ids:
            return None, None

        # peers that this space knows
        peer_ids = frozenset(scan_values.keys()) & self.peer_ids
        penalty = 0
        for peer_id, value in scan_values.items():
            if peer_id not in self.peer_ids:
                penalty += (value.rssi - no_signal)**2

        peers = tuple(self.peer_lookup[peer_id] for peer_id in peer_ids)
        values = np.array(tuple(scan_values[peer_id].rssi for peer_id in peer_ids), dtype=np.int64)

        # acceptable points need to have a value for the needed_peer_id
        points = tuple(
            np.argwhere(self.levels[:, self.peer_lookup[needed_peer_id]] > 0).ravel()
        )
        if not points:
            return None, None

        scores = (np.sum(
            (self.levels[np.array(points, dtype=np.uint32).reshape((-1, 1)), peers] - values)**2,
            axis=1
        )+penalty) / len(scan_values)
        best_point_i = np.argmin(scores).ravel()[0]
        best_point = points[best_point_i]
        return self.points[best_point], scores[best_point_i]
