from django.core.management.base import BaseCommand

from c3nav.mapdata.tasks import process_map_updates


class Command(BaseCommand):
    help = 'process unprocessed map updates'

    def handle(self, *args, **options):
        process_map_updates()
