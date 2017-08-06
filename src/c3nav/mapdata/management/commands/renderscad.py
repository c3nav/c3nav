from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'render the map to openscad'

    def handle(self, *args, **options):
        from c3nav.mapdata.models import Level
        Level.render_scad_all()
