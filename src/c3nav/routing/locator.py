import operator
import os
import pickle
import re
from collections import deque, namedtuple
from functools import reduce

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.models import Space


class Locator:
    filename = os.path.join(settings.CACHE_ROOT, 'locator')

    def __init__(self, stations, spaces):
        self.stations = stations
        self.spaces = spaces

    @classmethod
    def rebuild(cls):
        stations = LocatorStations()
        spaces = {}
        for space in Space.objects.prefetch_related('wifi_measurements'):
            spaces[space.pk] = LocatorSpace(
                LocatorPoint.from_measurement(measurement, stations)
                for measurement in space.wifi_measurements.all()
            )

        locator = cls(stations, spaces)
        pickle.dump(locator, open(cls.filename, 'wb'))
        return locator


class LocatorStations:
    def __init__(self):
        self.stations = []
        self.stations_lookup = {}

    def get_or_create(self, bssid, ssid, frequency):
        station_id = self.stations_lookup.get((bssid, ssid), None)
        if station_id is not None:
            station = self.stations[station_id]
            station.frequencies.add(frequency)
        else:
            station = LocatorStation(bssid, ssid, set((frequency, )))
            station_id = len(self.stations)
            self.stations_lookup[(bssid, ssid)] = station_id
            self.stations.append(station)
        return station_id


class LocatorSpace:
    def __init__(self, points):
        self.points = tuple(points)
        self.stations_set = reduce(operator.or_, (frozenset(point.values.keys()) for point in points), frozenset())
        self.stations = tuple(self.stations_set)
        self.stations_lookup = {station_id: i for i, station_id in enumerate(self.stations)}


class LocatorPoint(namedtuple('LocatorPoint', ('x', 'y', 'values'))):
    @classmethod
    def from_measurement(cls, measurement, stations: LocatorStations):
        return cls(x=measurement.geometry.x, y=measurement.geometry.y,
                   values=cls.convert_scans(measurement.data, stations))

    @classmethod
    def convert_scan(cls, scan, stations: LocatorStations):
        values = {}
        for scan_value in scan:
            station_id = stations.get_or_create(scan_value['bssid'], scan_value['ssid'], scan_value['frequency'])
            # todo: convert to something more or less linear
            values[station_id] = scan_value['level']
        return values

    @classmethod
    def convert_scans(cls, scans, stations: LocatorStations):
        values_list = deque()
        for scan in scans:
            values_list.append(cls.convert_scan(scan, stations))

        station_ids = reduce(operator.or_, (frozenset(values.keys()) for values in values_list), frozenset())
        return {
            station_id: sum(values.get(station_id, -100) for values in values_list) / len(values_list)
            for station_id in station_ids
        }

    valid_frequencies = frozenset((
        2412, 2417, 2422, 2427, 2432, 2437, 2442, 2447, 2452, 2457, 2462, 2467, 2472, 2484,
        5180, 5190, 5200, 5210, 5220, 5230, 5240, 5250, 5260, 5270, 5280, 5290, 5300, 5310, 5320,
        5500, 5510, 5520, 5530, 5540, 5550, 5560, 5570, 5580, 5590, 5600, 5610, 5620, 5630, 5640,
        5660, 5670, 5680, 5690, 5700, 5710, 5720, 5745, 5755, 5765, 5775, 5785, 5795, 5805, 5825
    ))
    invalid_scan = ValidationError(_('Invalid Scan.'))
    needed_keys = frozenset(('bssid', 'ssid', 'level', 'frequency'))
    allowed_keys = needed_keys | frozenset(('last', ))

    @classmethod
    def validate_scans(cls, data):
        if not isinstance(data, list):
            raise cls.invalid_scan
        for scan in data:
            cls.validate_scan(scan)

    @classmethod
    def validate_scan(cls, data):
        if not isinstance(data, list):
            raise cls.invalid_scan
        for scan_value in data:
            cls.validate_scan_value(scan_value)

    @classmethod
    def validate_scan_value(cls, data):
        if not isinstance(data, dict):
            raise cls.invalid_scan
        keys = frozenset(data.keys())
        if (keys - cls.allowed_keys) or (cls.needed_keys - keys):
            raise cls.invalid_scan
        if not re.match(r'^([0-9A-F]{2}:){5}[0-9A-F]{2}$', data['bssid']):
            raise cls.invalid_scan
        if not isinstance(data['level'], int) or not (-1 >= data['level'] >= -100):
            raise cls.invalid_scan
        if data['frequency'] not in cls.valid_frequencies:
            raise cls.invalid_scan
        if 'last' in keys and (not isinstance(data['last'], int) or data['last'] <= 0):
            raise cls.invalid_scan


class LocatorStation:
    def __init__(self, bssid, ssid, frequencies=()):
        self.bssid = bssid
        self.ssid = ssid
        self.frequencies = set(frequencies)

    def __repr__(self):
        return 'LocatorStation(%r, %r, frequencies=%r)' % (self.bssid, self.ssid, self.frequencies)
