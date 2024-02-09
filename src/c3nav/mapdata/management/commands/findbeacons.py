import numpy as np
from django.core.management.base import BaseCommand

from c3nav.mapdata.models.geometry.space import WifiMeasurement, RangingBeacon


class Command(BaseCommand):
    help = 'list FTM-capable APs that have been spotted'

    def handle(self, *args, **options):
        found_beacons = {}
        # lets collect them
        for wifi_measurement in WifiMeasurement.objects.select_related("space"):
            for measurement_list in wifi_measurement.data:
                for measurement in measurement_list:
                    if measurement.get("supports80211mc", False) or measurement.get("distance", None):
                        found_beacons.setdefault(measurement["bssid"], []).append((wifi_measurement, measurement))

        # put in the ones we know
        known = {r.bssid: r for r in RangingBeacon.objects.all()}

        # lets go through them
        for bssid, measurements in found_beacons.items():
            print(bssid, measurements[0][1]["ssid"], known.get(bssid))
            points = {wifi_measurement.geometry for wifi_measurement, measurement in measurements}
            for wifi_measurement, measurement in measurements:
                break
                #print(f"    Space={wifi_measurement.space.title!r} RSSI={measurement['rssi']} "
                #      f"distance={measurement.get('distance')} distance_sd={measurement.get('distance_sd')}")
