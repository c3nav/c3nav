from django.core.management.base import BaseCommand

from c3nav.mapdata.lastupdate import set_last_mapdata_update


class Command(BaseCommand):
    help = 'Clear the map cache (set last updated to now)'

    def handle(self, *args, **options):
        with set_last_mapdata_update():
            pass
