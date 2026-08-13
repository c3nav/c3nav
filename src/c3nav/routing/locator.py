from __future__ import annotations
import bisect
import math
import operator
import pickle
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cached_property, reduce
from itertools import chain, combinations
from operator import itemgetter
from typing import Annotated, NamedTuple, Union, Iterable, cast, Literal
from typing import Optional, Self, Sequence, TypeAlias
from uuid import UUID

import matplotlib.pyplot as plt
import numpy as np
from annotated_types import Lt
from django.conf import settings
from pydantic.types import NonNegativeInt
from pydantic_extra_types.mac_address import MacAddress
from shapely import Point, LineString, prepared, Polygon, MultiPolygon
from shapely.ops import nearest_points, unary_union
from shapely.plotting import plot_polygon
from shapely.affinity import scale

from c3nav.mapdata.models import MapUpdate, Space, Level
from c3nav.mapdata.models.geometry.space import AutoBeaconMeasurement, BeaconMeasurement, RangingBeacon
from c3nav.mapdata.utils.cache.stats import increment_cache_key
from c3nav.mapdata.utils.geometry import unwrap_geom, assert_multipolygon, assert_multilinestring, get_line_of_sight
from c3nav.mapdata.utils.index import Index
from c3nav.mapdata.utils.locations import CustomLocation
from c3nav.mapdata.utils.placement import PointPlacementHelper
from c3nav.mesh.utils import get_nodes_and_ranging_beacons
from c3nav.routing.router import Router, RouterSpace
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
    line_of_sight_area: LineOfSightArea = None
    extended_line_of_sight_area: LineOfSightArea = None

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


class RawRangeLocatorResult(NamedTuple):
    np_ranges: np.typing.NDArray
    dimensions: Literal[2, 3]
    xyz: tuple[int, int, int]
    precision: float
    space: RouterSpace | None = None


class LocatorResult(NamedTuple):
    location: Optional[CustomLocation]
    suggested_peers: list[RangePeerSchema]
    precision: Optional[float] = None
    analysis: Optional[list[str]] = None


@dataclass
class RealSpace:
    geometry: Polygon
    extended_geometry: Polygon | MultiPolygon
    space_ids: set[int]
    extend_to: set[int]

    @cached_property
    def geometry_prep(self):
        return prepared.prep(self.geometry)

    @cached_property
    def extended_geometry_prep(self):
        return prepared.prep(self.extended_geometry)

    def __getstate__(self):
        result = self.__dict__.copy()
        result.pop('geometry_prep', None)
        result.pop('extended_geometry_prep', None)
        return result


@dataclass
class LineOfSightArea:
    geometry: Polygon
    space_ids: frozenset[int]

    @cached_property
    def geometry_prep(self):
        return prepared.prep(self.geometry)

    def __getstate__(self):
        result = self.__dict__.copy()
        result.pop('geometry_prep', None)
        return result


@dataclass
class Locator:
    peers: list[LocatorPeer] = field(default_factory=list)
    peer_lookup: dict[TypedIdentifier, int] = field(default_factory=dict)
    xyz: np.array = field(default_factory=(lambda: np.empty((0,))))
    spaces: dict[int, "LocatorSpace"] = field(default_factory=dict)
    placement_helper: Optional[PointPlacementHelper] = None
    peers_with_80211mc: frozenset[int] = field(default_factory=frozenset)
    initial_80211mc_peers: list[int] = field(default_factory=list)
    real_spaces: list[RealSpace] = field(default_factory=list)
    space_to_real_space: dict[int, tuple[int, ...]] = field(default_factory=dict)

    @cached_property
    def initial_suggested_peers(self) -> list[RangePeerSchema]:
        return [self.peers[peer_id].suggestion for peer_id in self.initial_80211mc_peers]

    @classmethod
    def rebuild(cls, update, router):
        locator = cls()
        locator._rebuild(router)
        pickle.dump(locator, open(cls.build_filename(update), 'wb'))
        return locator

    def get_beacon_line_of_sight(self, beacon: RangingBeacon, real_space, plot=False):
        line_of_sight = get_line_of_sight(unwrap_geom(beacon.geometry), real_space, plot=plot)
        if line_of_sight is None:
            # todo: show warnigns for this stuff somewhere
            print("beacon outside space!", beacon, beacon.space.title)
            fix, ax = plt.subplots()
            plot_polygon(real_space, ax=ax, facecolor=(0, 0, 0, 0.6), add_points=False, linewidth=0)
            ax.scatter(x=[beacon.geometry.x], y=[beacon.geometry.y], c="red", s=30)
            plt.show()
            return real_space

        return line_of_sight

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

        self.space_to_real_space = {}
        self.real_spaces = []
        for level in Level.objects.prefetch_related("buildings", "spaces__columns", "spaces__holes"):
            buildings_geom = unary_union(tuple(unwrap_geom(building.geometry) for building in level.buildings.all()))
            level_real_spaces_geom = unary_union(tuple(  # noqa
                space.geometry.difference(unary_union((
                    *(unwrap_geom(column.geometry) for column in space.columns.all()
                      if column.access_restriction_id is None),
                    *((buildings_geom,) if space.outside else ()),
                ))) for space in level.spaces.all()
            ))

            level_real_spaces: list[RealSpace] = []
            for i, real_space in enumerate(assert_multipolygon(level_real_spaces_geom)):
                level_real_spaces.append(RealSpace(
                    geometry=real_space,
                    extended_geometry=real_space,
                    space_ids=set(),
                    extend_to=set(),
                ))

            # todo: speed this up using index
            for i, real_space in enumerate(level_real_spaces):
                real_space_buffered = real_space.geometry.buffer(0.5)
                for j, other_real_space in enumerate(level_real_spaces[i+1:], start=i+1):
                    if other_real_space.geometry_prep.intersects(real_space_buffered):
                        real_space.extend_to.add(j+len(self.real_spaces))
                        other_real_space.extend_to.add(i+len(self.real_spaces))
                if real_space.extend_to:
                    real_space.extended_geometry = unary_union((
                        real_space_buffered,
                        *(level_real_spaces[j-len(self.real_spaces)].geometry for j in real_space.extend_to),
                    ))

            for space in level.spaces.all():
                space_real_space = []
                for i, real_space in enumerate(level_real_spaces):
                    if real_space.geometry_prep.intersects(unwrap_geom(space.geometry)):
                        space_real_space.append(i+len(self.real_spaces))
                        real_space.space_ids.add(space.pk)
                self.space_to_real_space[space.pk] = tuple(space_real_space)

            self.real_spaces.extend(level_real_spaces)

        # go through beacons, create peers
        for beacon in calculated.beacons.values():
            xyz = self.get_beacon_xyz(beacon, router)

            real_spaces_i = self.space_to_real_space[beacon.space_id]
            for real_space_i in real_spaces_i:
                real_space = self.real_spaces[real_space_i]
                if real_space.geometry.intersects(unwrap_geom(beacon.geometry)):
                    area = self.get_beacon_line_of_sight(beacon, real_space.geometry)
                    extended_area = self.get_beacon_line_of_sight(beacon, real_space.extended_geometry)
                    line_of_sight_area = LineOfSightArea(
                        geometry=area,
                        space_ids=frozenset(
                            space_id for space_id in real_space.space_ids
                            if router.spaces[space_id].geometry_prep.intersects(area)
                        )
                    )
                    extended_line_of_sight_area = LineOfSightArea(
                        geometry=extended_area,
                        space_ids=frozenset(space_id for space_id in frozenset(chain(
                            real_space.space_ids,
                            chain.from_iterable(self.real_spaces[i].space_ids for i in real_space.extend_to),
                        )) if router.spaces[space_id].geometry_prep.intersects(extended_area)),
                    )
                    break
            else:
                line_of_sight_area = LineOfSightArea(
                    geometry=unwrap_geom(beacon.space.geometry),
                    space_ids=frozenset((beacon.space_id, )),
                )
                extended_line_of_sight_area = LineOfSightArea(
                    geometry=unwrap_geom(beacon.space.geometry),
                    space_ids=frozenset((beacon.space_id,)),
                )
                print("beacon outside of space", beacon, beacon.space.title)

            for identifier in self.get_beacon_identifiers(beacon):
                peer_id = self.get_peer_id(identifier, create=True)
                self.peers[peer_id].line_of_sight_area = line_of_sight_area
                self.peers[peer_id].extended_line_of_sight_area = extended_line_of_sight_area
                self.peers[peer_id].xyz = xyz
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

    @staticmethod
    def get_beacon_xyz(beacon: RangingBeacon, router: Router=None) -> tuple[int, int, int]:
        return (
            int(beacon.geometry.x * 100),
            int(beacon.geometry.y * 100),
            int(((router or Router.load()).altitude_for_point(beacon.space_id, beacon.geometry)
                 + float(beacon.altitude)) * 100),
        )

    @staticmethod
    def get_beacon_identifiers(beacon: RangingBeacon) -> list[TypedIdentifier]:
        identifiers = []
        for bssid in beacon.addresses:
            identifiers.append(TypedIdentifier(PeerType.WIFI, bssid.lower()))
        if beacon.ap_name:
            identifiers.append(TypedIdentifier(PeerType.WIFI, beacon.ap_name))
        if beacon.ibeacon_uuid and beacon.ibeacon_major is not None and beacon.ibeacon_minor is not None:
            identifiers.append(
                TypedIdentifier(PeerType.IBEACON, (beacon.ibeacon_uuid, beacon.ibeacon_major, beacon.ibeacon_minor))
            )
        return identifiers

    @staticmethod
    def get_scan_value_identifiers(scan_value: LocateWifiPeerSchema) -> Iterable[TypedIdentifier]:
        if settings.WIFI_SSIDS and scan_value.ssid not in settings.WIFI_SSIDS:
            return ()
        return (
           TypedIdentifier(PeerType.WIFI, scan_value.bssid.lower()),
           TypedIdentifier(PeerType.WIFI, scan_value.ap_name),
        )

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
            peer_ids = {
                self.get_peer_id(identifier) for identifier in self.get_scan_value_identifiers(scan_value)
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
    def load(cls) -> Self:
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
               correct_xyz: Optional[tuple[int, int, int]] = None, stats=False, debug=settings.DEBUG) -> LocatorResult:
        # todo: support for ibeacons
        scan_data = self.convert_raw_scan_data(raw_scan_data)

        result = self.locate_range(scan_data, permissions, correct_xyz=correct_xyz, stats=stats, debug=debug)
        if result.location is not None:
            if stats:
                increment_cache_key('apistats__locatemethod__range')
            return result

        suggestions = result.suggested_peers

        if not scan_data:
            return LocatorResult(location=None, suggested_peers=suggestions)

        result = self.locate_by_beacon_positions(scan_data, permissions)
        if result is not None:
            if stats:
                increment_cache_key('apistats__locatemethod__beaconpositions')
            return LocatorResult(location=result, suggested_peers=suggestions)

        result = self.locate_rssi(scan_data, permissions)
        if result is not None:
            if stats:
                increment_cache_key('apistats__locatemethod__rssi')
        return LocatorResult(location=result, suggested_peers=suggestions)

    def locate_by_beacon_positions(self, scan_data: ScanData, permissions=None) -> Optional[CustomLocation]:
        # todo: use the line of sight things here
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

        # if we are outside a space, let's move the user into the space
        new_level, new_point = self.move_into_space(
            router=router, level=level, point=point, restrictions=restrictions,
            max_space_distance=20,
        )

        if new_point is not None:
            level = new_level
            point = new_point

        return CustomLocation(
            level=level,
            x=point.x,
            y=point.y,
            permissions=permissions,
            icon='my_location'
        )

    def locate_rssi(self, scan_data: ScanData, permissions=None) -> Optional[CustomLocation]:
        # todo: use the line of sight things here
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

    def move_into_space(self, router: "Router", level: "Level", point: Point, restrictions,
                        max_space_distance: int | float = 20,
                        drop_down_through_holes=False) -> tuple["Level", "Point"]:
        new_space, new_point = self.placement_helper.get_point_and_space(
            level_id=level.pk, point=point, restrictions=restrictions,
            max_space_distance=max_space_distance,
            drop_down_through_holes=drop_down_through_holes,
        )
        if new_space is not None:
            level = router.levels[new_space.level_id]
        if level.on_top_of_id:
            level = router.levels[level.on_top_of_id]
        return level, new_point

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

    def _pre_locate_range(self, scan_data: ScanData) -> tuple[tuple[int, ...], LocatorResult | None]:
        peer_ids = self._deduplicate_peer_ids(
            tuple(i for i, item in scan_data.items() if i < len(self.xyz) and item.distance and item.distance > -5)
        )

        # ignore everything with distance over 75m
        #peer_ids = tuple(peer_id for peer_id in peer_ids if scan_data[peer_id].distance < 75)

        if not peer_ids:
            return peer_ids, LocatorResult(
                location=None,
                suggested_peers=self.initial_suggested_peers
            )

        if len(peer_ids) == 1:
            return peer_ids, LocatorResult(
                location=None,
                suggested_peers=(
                        [self.peers[pid].suggestion for pid, c in self.peers[peer_ids[0]].seen_with.most_common(20)]
                        or self.initial_suggested_peers
                )
            )

        if len(peer_ids) == 2:
            # todo: maybe we can at least give something?
            return peer_ids, LocatorResult(
                location=None,
                suggested_peers=(
                        [self.peers[pid].suggestion
                         for pid, c in
                         self.peers[min(peer_ids)].seen_with_with.get(max(peer_ids), Counter()).most_common(20)]
                        or self.initial_suggested_peers
                ),
            )

        return peer_ids, None

    def _raw_locate_range(self, peer_ids: tuple[int, ...], scan_data: ScanData,
                          debug=settings.DEBUG) -> RawRangeLocatorResult:

        if len(peer_ids) == 3:
            if debug:
                print('2D trilateration')
            dimensions = 2
        else:
            if debug:
                print('3D trilateration')
            dimensions = 3

        relevant_xyz = self.xyz[peer_ids, :]

        # create 2d array with x, y, z, distance as rows
        np_ranges = np.hstack((
            relevant_xyz,
            np.array(tuple(float(scan_data[i].distance) for i in peer_ids)).reshape((-1, 1))*100,
        ))

        #print(np_ranges)

        measured_ranges = np.clip(np_ranges[:, 3], a_min=0, a_max=None)
        #print('a', measured_ranges)
        # measured_ranges[measured_ranges<1] = 1
        #print('b', measured_ranges)

        if debug:
            print("relevant", relevant_xyz)
            print("measured_ranges", measured_ranges)

        rssis = np.array(tuple(scan_data[i].rssi for i in peer_ids))
        inaccurate_bonus = np.array([scan_data[i].distance_sd == 0.15 for i in peer_ids])

        factors = np.ones(rssis.shape)
        factors[measured_ranges > 7500] = 0.3  # over 75m measurements are less accurate – this factor is better than 0.5

        router = Router.load()

        # select the space – this is currently our main optimization: todo: make this more performant?
        strongest_measurements = sorted(scan_data.items(), key=lambda a: a[1].rssi, reverse=True)
        strongest_peer = self.peers[strongest_measurements[0][0]]
        strongest_router_space = router.spaces[strongest_peer.space_id]

        line_of_sight_area = (
            strongest_peer.line_of_sight_area
            if strongest_measurements[0][1].rssi > -50 # todo: be smarter about making this decision
            else strongest_peer.extended_line_of_sight_area
        )

        minx, miny, maxx, maxy = (int(i * 100) for i in line_of_sight_area.geometry.bounds)

        # rating the guess by calculating the distances
        # negative if the measured distance is higher than it should be for this guess
        def add_to_guess(guess):
            if len(guess) > 2:
                return guess
            point = Point(*guess)
            return np.array(
                (*guess, int(strongest_router_space.altitudearea_for_point(point).get_altitude(point)*100))
            )

        def diff_func(guess):
            result = self.norm_func(np_ranges[:, :3] - guess, axis=1)
            # print(result)
            return result
            # factors = self.norm_func(np_ranges[:, :dimensions] - guess[:dimensions], axis=1) / measured_ranges
            # return factors - np.mean(factors)

        def cost_func(guess):
            if debug:
                print("guess", guess)

            guess_distances = diff_func(add_to_guess(guess))
            inaccuracy_cm = measured_ranges - guess_distances  # negative if it's measured closer than should be possible
            inaccuracy = inaccuracy_cm
            #inaccuracy = (measured_ranges / guess_distances) - 1

            if debug:
                print("diff", inaccuracy)


            max_inaccuracy = np.argmax(inaccuracy)

            # for access points more than 10m (=1000cm) away, we don't allow the offset to be below -2m (=-200cm)
            # but, somehow, this works better if the threshold is at +200cm. why?
            # this is one of the most important optimizations
            too_far_select = (inaccuracy_cm < -500) | ((guess_distances > 1000) & (inaccuracy_cm < -200))
            if debug:
                print("too_far_select", too_far_select)
            inaccuracy[(inaccuracy_cm < 0)] *= 100

            # time to factor bad measurements less – this also helps quite a bit
            inaccuracy *= factors

            #this_bonus = ~too_far_select & inaccurate_bonus
            #inaccuracy[this_bonus] /= 8

            if debug:
                print("corrected offset", inaccuracy)

            cost = np.sum((inaccuracy ** 2))

            if not line_of_sight_area.geometry_prep.intersects(Point(*guess[:2]/100)):
                cost *= 5000

            if debug:
                print("cost", inaccuracy, cost)
            return cost

        if dimensions == 3:
            minz, maxz = strongest_router_space.minz_maxz
        else:
            if (len(strongest_router_space.altitudeareas) == 1
                    and strongest_router_space.altitudeareas[0].altitude is not None):
                minz = maxz = int(strongest_router_space.altitudeareas[0].altitude * 100)
            else:
                minz = maxz = None

        bounds = ((minx, maxx), (miny, maxy), *(((minz, maxz), ) if minz is not None else ()))

        initial_guess = tuple((mini+maxi)/2 for mini, maxi in bounds)

        #bounds = tuple(zip(min_xyz[:2], max_xyz[:2]))

        #if dimensions == 3:
        #    bounds += ((min(relevant_xyz[:, 2]), max(relevant_xyz[:, 2])),)

        results = self.least_squares_func(
            fun=cost_func,
            # jac="3-point",
            #loss="linear",
            bounds=bounds,
            #x_scale=10,
            x0=initial_guess,
            tol=0.1,
        )

        # create result
        result_x = tuple(add_to_guess(results.x))

        # move point into line of sight area if needed
        point = Point(*(i/100 for i in result_x[:2]))
        if not strongest_peer.line_of_sight_area.geometry_prep.intersects(point):
            # todo: this buffer operation could be somewhere else to be faster
            point = nearest_points(strongest_peer.line_of_sight_area.geometry.buffer(-0.05), Point(point))[0]
            result_x = (int(point.x*100), int(point.y*100), result_x[2])

        # determine space
        if len(strongest_peer.line_of_sight_area.space_ids) > 1:
            if not strongest_router_space.geometry_prep.intersects(point):
                for space_id in strongest_peer.line_of_sight_area.space_ids - {strongest_router_space.id}:
                    space = router.spaces[space_id]
                    if space.geometry_prep.intersects(point):
                        strongest_router_space = space

        precision = round(float(np.std(diff_func(result_x) - measured_ranges)) / 100, 2)

        return RawRangeLocatorResult(
            np_ranges=np_ranges,
            dimensions=cast(Literal[2, 3], dimensions),
            xyz=cast(tuple[int, int, int], result_x),
            precision=precision,
        )

    def raw_locate_range(self, scan_data: ScanData, debug=settings.DEBUG) -> RawRangeLocatorResult | None:
        peer_ids, result = self._pre_locate_range(scan_data)
        if result is not None:
            return None

        return self._raw_locate_range(peer_ids, scan_data, debug)


    def locate_range(self, scan_data: ScanData, permissions=None, orig_addr=None,
                     correct_xyz: Optional[tuple[int, int, int]] = None, stats=False,
                     debug=settings.DEBUG) -> LocatorResult:
        peer_ids, result = self._pre_locate_range(scan_data)
        if result is not None:
            return result

        np_ranges, dimensions, result_x, precision, located_space = self._raw_locate_range(peer_ids, scan_data, debug)

        result_pos = tuple(i/100 for i in result_x)

        router = Router.load()
        restrictions = router.get_restrictions(permissions)

        result_distances = self.norm_func(np_ranges[:, :dimensions] - result_x[:dimensions], axis=1)/100

        point = Point(result_pos[0], result_pos[1])

        if located_space is None or located_space.id in restrictions.spaces:
            level = router.levels[router.level_id_for_xyz(
                # -1.3m cause we assume people to be above ground
                (result_pos[0], result_pos[1], result_pos[2] - (1.3 if dimensions == 3 else 0)),
                restrictions=None, # yeah this is right
            )]
        else:
            level = router.levels[located_space.level_id]

        if level.on_top_of_id:
            level = router.levels[level.on_top_of_id]

        # analyse
        analysis = []
        if correct_xyz is not None:
            distance = float(np.linalg.norm(result_x[:dimensions] - np.array(correct_xyz[:dimensions])))/100
            distance_2d = float(np.linalg.norm(result_x[:2] - np.array(correct_xyz[:2]))) / 100

            analysis.append(
                f"{tuple(round(float(i)/100, 2) for i in correct_xyz)} → "
                f"({dimensions}D) {tuple(round(float(i)/100, 2) for i in result_x)}"
                f"(off by {distance:.2f} m" + (f" (2D: {distance_2d:.2f} m" if dimensions > 2 else "") + ")"
            )
            correct_distances = np.linalg.norm(self.xyz[peer_ids, :] - np.array(correct_xyz), axis=1) / 100
        else:
            correct_distances = (None,) * len(peer_ids)

        for peer_id, result_distance, correct_distance in zip(peer_ids, result_distances, correct_distances):
            peer = self.peers[peer_id]
            value = scan_data[peer_id]
            analysis.append(f"{tuple(round(float(i)/100, 2) for i in peer.xyz)}: "
                            f"{value.distance:.2f} m (sd: {value.distance_sd:.2f} m) - {value.rssi} dB")
            analysis.append(f" → result: {round(float(result_distance), 2):.2f} m"
                            f" ({value.distance-result_distance:+.1f} m)" +
                            (f" → correct: {correct_distance:.2f} m"
                             f" ({value.distance-correct_distance:+.1f} m)"
                             f" → {correct_distance-result_distance:+.1f} m" if correct_distance is not None else ""))

        # if we are outside a space, let's move the user into the space
        if located_space is None or located_space.id in restrictions.spaces:
            new_level, new_point = self.move_into_space(
                router=router, level=level, point=point,
                restrictions=restrictions, max_space_distance=20,
            )
        else:
            new_level, new_point = None, None

        if new_point is not None:
            level = new_level
            point = new_point

            # point may have been moved so we need to update the precision too
            precision = round(precision + np.linalg.norm((new_point.x-point.x, new_point.y-point.y)), 2)

        # create location
        location = CustomLocation(
            level=level,
            x=point.x,
            y=point.y,
            permissions=permissions,
            icon='my_location'
        )
        location.z = result_pos[2]

        # get suggested peers
        remaining_peer_ids = tuple(self.peers_with_80211mc - set(peer_ids))
        #print(remaining_peer_ids, self.xyz)
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
        if debug:
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
            #print("diff result-measured:", ", ".join(
            #    ("%.2f" % i) for i in
            #    tuple(diff_func(result_pos))
            #))
            #if orig_xyz is not None:
            #    print("diff correct-measured:", ", ".join(
            #        ("%.2f" % i) for i in
            #        tuple(diff_func(orig_xyz))
             #   ))

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

        if stats:
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
