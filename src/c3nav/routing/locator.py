import operator
import os
import pickle
import re
import threading
from collections import deque, namedtuple
from functools import reduce

import numpy as np
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.models import MapUpdate, Space
from c3nav.mapdata.utils.locations import CustomLocation
from c3nav.routing.router import Router


class Locator:
    filename = os.path.join(settings.CACHE_ROOT, 'locator')

    def __init__(self, stations, spaces):
        self.stations = stations
        self.spaces = spaces

    @classmethod
    def rebuild(cls, update):
        stations = LocatorStations()
        spaces = {}
        for space in Space.objects.prefetch_related('wifi_measurements'):
            new_space = LocatorSpace(
                LocatorPoint.from_measurement(measurement, stations)
                for measurement in space.wifi_measurements.all()
            )
            if new_space.points:
                spaces[space.pk] = new_space

        locator = cls(stations, spaces)
        pickle.dump(locator, open(cls.build_filename(update), 'wb'))
        return locator

    @classmethod
    def build_filename(cls, update):
        return os.path.join(settings.CACHE_ROOT, 'locator_%s.pickle' % MapUpdate.build_cache_key(*update))

    @classmethod
    def load_nocache(cls, update):
        return pickle.load(open(cls.build_filename(update), 'rb'))

    cached = None
    cache_update = None
    cache_lock = threading.Lock()

    @classmethod
    def load(cls):
        from c3nav.mapdata.models import MapUpdate
        update = MapUpdate.last_processed_update()
        if cls.cache_update != update:
            with cls.cache_lock:
                cls.cache_update = update
                cls.cached = cls.load_nocache(update)
        return cls.cached

    def locate(self, scan, permissions=None):
        router = Router.load()
        restrictions = router.get_restrictions(permissions)

        scan = LocatorPoint.clean_scan(scan, ignore_invalid_stations=True)
        scan_values = LocatorPoint.convert_scan(scan, self.stations, create=False)
        station_ids = frozenset(scan_values.keys())

        spaces = tuple((pk, space, station_ids & space.stations_set)
                       for pk, space in self.spaces.items()
                       if pk not in restrictions.spaces)
        spaces = tuple((pk, space, station_ids) for pk, space, station_ids in spaces if station_ids)
        if not spaces:
            return None
        good_spaces = tuple((pk, space, station_ids) for pk, space, station_ids in spaces if len(station_ids) >= 3)
        if not good_spaces:
            for station_id in station_ids:
                scan_values[station_id] = 0
            good_spaces = spaces

        good_spaces = sorted(good_spaces, key=lambda item: len(item[2]), reverse=True)[:10]

        best_location = None
        best_score = float('inf')

        for pk, space, station_ids in good_spaces:
            point, score = space.get_best_point(scan_values, station_ids)
            if score < best_score:
                location = CustomLocation(router.spaces[pk].level, point.x, point.y,
                                          permissions=permissions, icon='my_location')
                best_location = location
                best_score = score

        return best_location


class LocatorStations:
    def __init__(self):
        self.stations = []
        self.stations_lookup = {}

    def get(self, bssid, ssid, frequency, create=False):
        station_id = self.stations_lookup.get((bssid, ssid), None)
        if station_id is not None:
            station = self.stations[station_id]
            station.frequencies.add(frequency)
        elif create:
            station = LocatorStation(bssid, ssid, set((frequency, )))
            station_id = len(self.stations)
            self.stations_lookup[(bssid, ssid)] = station_id
            self.stations.append(station)
        return station_id


class LocatorSpace:
    def __init__(self, points):
        self.points = tuple(points)
        self.stations_set = reduce(operator.or_, (frozenset(point.values.keys()) for point in self.points), frozenset())
        self.stations = tuple(self.stations_set)
        self.stations_lookup = {station_id: i for i, station_id in enumerate(self.stations)}

        self.levels = np.full((len(self.points), len(self.stations)), fill_value=-100, dtype=np.int16)
        for i, point in enumerate(self.points):
            for station_id, value in point.values.items():
                self.levels[i][self.stations_lookup[station_id]] = value

    def get_best_point(self, scan_values, station_ids):
        stations = tuple(self.stations_lookup[station_id] for station_id in station_ids)
        values = np.array(tuple(scan_values[station_id] for station_id in station_ids), dtype=np.int16)
        scores = np.sum((self.levels[:, stations]-values)**2, axis=1)
        best_point = np.argmin(scores).ravel()[0]
        return self.points[best_point], scores[best_point]


class LocatorPoint(namedtuple('LocatorPoint', ('x', 'y', 'values'))):
    @classmethod
    def from_measurement(cls, measurement, stations: LocatorStations):
        return cls(x=measurement.geometry.x, y=measurement.geometry.y,
                   values=cls.convert_scans(measurement.data, stations, create=True))

    @classmethod
    def convert_scan(cls, scan, stations: LocatorStations, create=False):
        values = {}
        for scan_value in scan:
            if settings.WIFI_SSIDS and scan_value['ssid'] not in settings.WIFI_SSIDS:
                continue
            station_id = stations.get(bssid=scan_value['bssid'], ssid=scan_value['ssid'],
                                      frequency=scan_value['frequency'], create=create)
            if station_id is not None:
                # todo: convert to something more or less linear
                values[station_id] = scan_value['level']
        return values

    @classmethod
    def convert_scans(cls, scans, stations: LocatorStations, create=False):
        values_list = deque()
        for scan in scans:
            values_list.append(cls.convert_scan(scan, stations, create))

        station_ids = reduce(operator.or_, (frozenset(values.keys()) for values in values_list), frozenset())
        return {
            station_id: cls.average(tuple(values[station_id] for values in values_list if station_id in values))
            for station_id in station_ids
        }

    @staticmethod
    def average(items):
        return sum(items) / len(items)

    valid_frequencies = frozenset((
        2412, 2417, 2422, 2427, 2432, 2437, 2442, 2447, 2452, 2457, 2462, 2467, 2472, 2484,
        5180, 5190, 5200, 5210, 5220, 5230, 5240, 5250, 5260, 5270, 5280, 5290, 5300, 5310, 5320,
        5500, 5510, 5520, 5530, 5540, 5550, 5560, 5570, 5580, 5590, 5600, 5610, 5620, 5630, 5640,
        5660, 5670, 5680, 5690, 5700, 5710, 5720, 5745, 5755, 5765, 5775, 5785, 5795, 5805, 5825
    ))
    needed_keys = frozenset(('bssid', 'ssid', 'level', 'frequency'))
    allowed_keys = needed_keys | frozenset(('last', ))

    @classmethod
    def clean_scans(cls, data, ignore_invalid_stations=False):
        if not isinstance(data, list):
            raise ValidationError(_('Invalid Scan. Scans list list not a list.'))
        return tuple(cls.clean_scan(scan) for scan in data)

    @classmethod
    def clean_scan(cls, data, ignore_invalid_stations=False):
        if not isinstance(data, list):
            raise ValidationError(_('Invalid Scan. Scan not a list.'))
        cleaned_scan = deque()
        for scan_value in data:
            try:
                cleaned_scan.append(cls.clean_scan_value(scan_value))
            except ValidationError:
                if not ignore_invalid_stations:
                    raise
        return tuple(cleaned_scan)

    @classmethod
    def clean_scan_value(cls, data):
        if not isinstance(data, dict):
            raise ValidationError(_('Invalid Scan. Scan value not a dictionary.'))
        keys = frozenset(data.keys())
        if (keys - cls.allowed_keys) or (cls.needed_keys - keys):
            raise ValidationError(_('Invalid Scan. Missing or forbidden keys.'))
        if not isinstance(data['bssid'], str):
            raise ValidationError(_('Invalid Scan. BSSID not a String.'))
        data['bssid'] = data['bssid'].upper()
        if not re.match(r'^([0-9A-F]{2}:){5}[0-9A-F]{2}$', data['bssid']):
            raise ValidationError(_('Invalid Scan. Invalid BSSID.'))
        if not isinstance(data['level'], int) or not (-1 >= data['level'] >= -100):
            raise ValidationError(_('Invalid Scan. Invalid RSSI/Level.'))
        if data['frequency'] not in cls.valid_frequencies:
            raise ValidationError(_('Invalid Scan. Not an allowed frequency.'))
        if 'last' in keys and (not isinstance(data['last'], int) or data['last'] <= 0):
            raise ValidationError(_('Invalid Scan. Invalid last timestamp.'))
        return data


class LocatorStation:
    def __init__(self, bssid, ssid, frequencies=()):
        self.bssid = bssid
        self.ssid = ssid
        self.frequencies = set(frequencies)

    def __repr__(self):
        return 'LocatorStation(%r, %r, frequencies=%r)' % (self.bssid, self.ssid, self.frequencies)
