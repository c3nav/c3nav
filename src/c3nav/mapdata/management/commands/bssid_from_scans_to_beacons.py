from django.core.management.base import BaseCommand
from django.db import transaction

from c3nav.mapdata.models.geometry.space import BeaconMeasurement


class Command(BaseCommand):
    help = 'collect BSSIDS for AP names from measurements'

    def handle(self, *args, **options):
        with transaction.atomic():
            BeaconMeasurement.contribute_bssid_to_beacons(BeaconMeasurement.objects.all())