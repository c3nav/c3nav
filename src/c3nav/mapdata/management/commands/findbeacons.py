import numpy as np
from django.core.management.base import BaseCommand

from c3nav.mapdata.models.geometry.space import BeaconMeasurement, RangingBeacon


class Command(BaseCommand):
    help = 'list FTM-capable APs that have been spotted'

    def handle(self, *args, **options):
        found_beacons = {}
        # lets collect them
        for beacon_measurement in BeaconMeasurement.objects.select_related("space"):
            for measurement_list in beacon_measurement.data:
                for measurement in measurement_list:
                    if measurement.get("supports80211mc", False) or measurement.get("distance", None):
                        found_beacons.setdefault(measurement["bssid"], []).append((beacon_measurement, measurement))

        # put in the ones we know
        known = {r.wifi_bssid: r for r in RangingBeacon.objects.all()}

        # lets go through them
        for bssid, measurements in found_beacons.items():
            print(bssid, measurements[0][1]["ssid"], known.get(bssid))
            points = {beacon_measurement.geometry for beacon_measurement, measurement in measurements}
            for beacon_measurement, measurement in measurements:
                break
                #print(f"    Space={wifi_measurement.space.title!r} RSSI={measurement['rssi']} "
                #      f"distance={measurement.get('distance')} distance_sd={measurement.get('distance_sd')}")
