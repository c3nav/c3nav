import csv
import json
import math
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
    help = 'export wifi scandata'

    def handle(self, *args, **options):

        locator = Locator.load()
        identifier_to_beacon: dict[TypedIdentifier, int] = {}
        beacons: dict[int, RangingBeacon] = {}
        beacons_xyz: dict[int, np.typing.NDArray] = {}
        for beacon in RangingBeacon.objects.select_related("space"):
            beacons[beacon.pk] = beacon
            beacons_xyz[beacon.pk] = np.array(locator.get_beacon_xyz(beacon))
            identifiers = locator.get_beacon_identifiers(beacon)
            identifier_to_beacon.update(dict(zip(identifiers, repeat(beacon.pk))))

        with open('/tmp/wifiexport.csv', 'w', newline='') as csvfile:
            spamwriter = csv.writer(csvfile)
            spamwriter.writerow(["measurement", "actual x", "actual y", "actual z", "distance", "responder x", "responder y", "responder z", "responder"])

            k = 0
            for measurement in cast(Iterable[BeaconMeasurement], BeaconMeasurement.objects.select_related("space")):
                for scan in measurement.data.wifi:
                    k += 1
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
                        spamwriter.writerow([
                            k, *(i/100 for i in measurement.correct_xyz), scan_value.distance,
                            *(i/100 for i in beacons_xyz[beacon_id]), beacon_id,
                        ])
