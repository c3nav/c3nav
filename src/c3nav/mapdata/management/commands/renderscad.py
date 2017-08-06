import os
from django.conf import settings
from django.core.management.base import BaseCommand

from c3nav.mapdata.utils.scad import polygon_scad


class Command(BaseCommand):
    help = 'render the map to openscad'

    def handle(self, *args, **options):
        from c3nav.mapdata.models import AltitudeArea
        filename = os.path.join(settings.RENDER_ROOT, 'all.scad')
        with open(filename, 'w') as f:
            for area in AltitudeArea.objects.all():
                f.write('translate([0, 0, %.2f]) ' % area.altitude)
                f.write(polygon_scad(area.geometry)+';\n')
