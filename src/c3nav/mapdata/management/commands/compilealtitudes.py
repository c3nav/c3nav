from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'recalculate the map altitudes'

    def handle(self, *args, **options):
        from c3nav.mapdata.models import AltitudeArea
        AltitudeArea.recalculate()
