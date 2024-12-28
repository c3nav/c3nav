import operator
import pickle
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cached_property, reduce
from typing import Annotated, NamedTuple, Union
from typing import Optional, Self, Sequence, TypeAlias
from uuid import UUID

import numpy as np
from annotated_types import Lt
from django.conf import settings
from pydantic.types import NonNegativeInt
from pydantic_extra_types.mac_address import MacAddress

from c3nav.mapdata.models import MapUpdate, Space
from c3nav.mapdata.utils.locations import CustomLocation
from c3nav.mesh.utils import get_nodes_and_ranging_beacons
from c3nav.routing.router import Router
from c3nav.routing.schemas import LocateWifiPeerSchema, BeaconMeasurementDataSchema, LocateIBeaconPeerSchema

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
    frequencies: set[int] = field(default_factory=set)
    xyz: Optional[tuple[int, int, int]] = None
    space_id: Optional[int] = None


@dataclass
class ScanDataValue:
    rssi: Optional[int] = None
    ibeacon_range: Optional[float] = None
    distance: Optional[float] = None

    @classmethod
    def average(cls, items: Sequence[Self]):
        rssi = [item.rssi for item in items if item.rssi]
        ibeacon_range = [item.ibeacon_range for item in items if item.ibeacon_range is not None]
        distance = [item.distance for item in items if item.distance is not None]
        return cls(
            rssi=(sum(rssi)//len(rssi)) if rssi else None,
            ibeacon_range=(sum(ibeacon_range) // len(ibeacon_range)) if ibeacon_range else None,
            distance=(sum(distance)/len(distance)) if distance else None,
        )


ScanData: TypeAlias = dict[int, ScanDataValue]


@dataclass
class LocatorPoint:
    x: float
    y: float
    values: ScanData


@dataclass
class Locator:
    peers: list[LocatorPeer] = field(default_factory=list)
    peer_lookup: dict[TypedIdentifier, int] = field(default_factory=dict)
    xyz: np.array = field(default_factory=(lambda: np.empty((0,))))
    spaces: dict[int, "LocatorSpace"] = field(default_factory=dict)

    @classmethod
    def rebuild(cls, update, router):
        locator = cls()
        locator._rebuild(router)
        pickle.dump(locator, open(cls.build_filename(update), 'wb'))
        return locator

    def _rebuild(self, router):
        calculated = get_nodes_and_ranging_beacons()
        for beacon in calculated.beacons.values():
            identifiers = []
            for bssid in beacon.addresses:
                identifiers.append(TypedIdentifier(PeerType.WIFI, bssid))
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
                self.peers[peer_id].space_id = beacon.space_id
        self.xyz = np.array(tuple(peer.xyz for peer in self.peers))

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
                self.get_peer_id(TypedIdentifier(PeerType.WIFI, scan_value.bssid), create=create_peers),
                self.get_peer_id(TypedIdentifier(PeerType.WIFI, scan_value.ap_name), create=create_peers),
            } - {None, ""}
            for peer_id in peer_ids:
                result[peer_id] = ScanDataValue(rssi=scan_value.rssi, distance=scan_value.distance)
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

    def get_all_nodes_xyz(self) -> dict[TypedIdentifier, tuple[float, float, float]]:
        return {
            peer.identifier: peer.xyz for peer in self.peers[:len(self.xyz)]
            if isinstance(peer.identifier, MacAddress)
        }

    def locate(self, raw_scan_data: list[LocateWifiPeerSchema], permissions=None):
        # todo: support for ibeacons
        scan_data = self.convert_raw_scan_data(raw_scan_data)
        if not scan_data:
            return None

        result = self.locate_range(scan_data, permissions)
        if result is not None:
            return result

        result = self.locate_by_beacon_positions(scan_data, permissions)
        if result is not None:
            return result

        return self.locate_rssi(scan_data, permissions)

    def locate_by_beacon_positions(self, scan_data: ScanData, permissions=None):
        scan_data_we_can_use = [
            (peer_id, value) for peer_id, value in scan_data.items() if self.peers[peer_id].space_id
        ]

        if not scan_data_we_can_use:
            return None

        router = Router.load()

        # get visible spaces
        best_ap_id = max(scan_data_we_can_use, key=lambda item: item[1].rssi)[0]
        space_id = self.peers[best_ap_id].space_id
        space = router.spaces[space_id]

        scan_data_in_the_same_room = sorted([
            (peer_id, value) for peer_id, value in scan_data_we_can_use if self.peers[peer_id].space_id == space_id
        ], key=lambda a: -a[1].rssi)

        deduplicized_scan_data_in_the_same_room = []
        already_got = set()
        for peer_id, value in scan_data_in_the_same_room:
            key = tuple(self.peers[peer_id].xyz)
            if key in already_got:
                continue
            deduplicized_scan_data_in_the_same_room.append((peer_id, value))

        the_sum = sum((value.rssi + 90) for peer_id, value in scan_data_in_the_same_room[:3])

        if not the_sum:
            point = space.point
            return CustomLocation(
                level=router.levels[space.level_id],
                x=point.x,
                y=point.y,
                permissions=permissions,
                icon='my_location'
            )
        else:
            x = 0
            y = 0
            for peer_id, value in scan_data_in_the_same_room[:3]:
                x += float(self.peers[peer_id].xyz[0]) * (value.rssi+90) / the_sum
                y += float(self.peers[peer_id].xyz[1]) * (value.rssi+90) / the_sum
            return CustomLocation(
                level=router.levels[space.level_id],
                x=x/100,
                y=y/100,
                permissions=permissions,
                icon='my_location'
            )

    def locate_rssi(self, scan_data: ScanData, permissions=None):
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
        from scipy.optimize import least_squares
        return least_squares

    @cached_property
    def norm_func(self):
        # this is effectively a lazy import to save memory… todo: do we need that?
        from scipy.linalg import norm
        return norm

    def locate_range(self, scan_data: ScanData, permissions=None, orig_addr=None):
        peer_ids = tuple(i for i, item in scan_data.items() if i < len(self.xyz) and item.distance)

        if len(peer_ids) < 3:
            # can't get a good result from just two beacons
            # todo: maybe we can at least give… something?
            print('less than 3 ranges, can\'t do ranging')
            return None

        if len(peer_ids) == 3 and 0:
            print('2D trilateration')
            dimensions = 2
        else:
            print('3D trilateration')
            dimensions = 3

        relevant_xyz = self.xyz[peer_ids, :]

        # create 2d array with x, y, z, distance as rows
        np_ranges = np.hstack((
            relevant_xyz,
            np.array(tuple(float(scan_data[i].distance) for i in peer_ids)).reshape((-1, 1)),
        ))

        #print(np_ranges)

        measured_ranges = np_ranges[:, 3]
        #print('a', measured_ranges)
        # measured_ranges[measured_ranges<1] = 1
        #print('b', measured_ranges)

        # rating the guess by calculating the distances
        def diff_func(guess):
            result = self.norm_func(np_ranges[:, :dimensions] - guess[:dimensions], axis=1) - measured_ranges
            # print(result)
            return result
            # factors = self.norm_func(np_ranges[:, :dimensions] - guess[:dimensions], axis=1) / measured_ranges
            # return factors - np.mean(factors)

        def cost_func(guess):
            result = np.abs(diff_func(guess))
            result[result < 300] = result[result < 300]/3+200
            return result

        # initial guess i the average of all beacons, with scale 1
        initial_guess = np.average(np_ranges[:, :dimensions], axis=0)

        # here the magic happen
        results = self.least_squares_func(
            fun=cost_func,
            # jac="3-point",
            loss="linear",
            bounds=(
                np.min(self.xyz[:, :dimensions], axis=0) - np.array([200, 200, 100])[:dimensions],
                np.max(self.xyz[:, :dimensions], axis=0) + np.array([200, 200, 100])[:dimensions],
            ),
            x0=initial_guess,
        )

        # create result
        router = Router.load()
        restrictions = router.get_restrictions(permissions)

        result_pos = results.x
        location = CustomLocation(
            level=router.levels[router.level_id_for_xyz(
                (result_pos[0], result_pos[1], result_pos[2]-1.3),  # -1.3m cause we assume people to be above ground
                restrictions
            )],
            x=result_pos[0]/100,
            y=result_pos[1]/100,
            permissions=permissions,
            icon='my_location'
        )
        location.z = result_pos[2]/100

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
