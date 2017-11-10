from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.tasks import process_map_updates


class Command(BaseCommand):
    help = 'process unprocessed map updates'

    def handle(self, *args, **options):
        process_map_updates()

        if not settings.HAS_REAL_CACHE:
            print(_('You have no external cache configured, so don\'t forget to restart your c3nav instance!'))
