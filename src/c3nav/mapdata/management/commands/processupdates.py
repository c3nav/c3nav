from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.translation import gettext_lazy as _

from c3nav.mapdata.updatejobs import run_mapupdate_jobs


class Command(BaseCommand):
    help = 'process unprocessed map updates'

    def handle(self, *args, **options):
        run_mapupdate_jobs()

        if not settings.HAS_REAL_CACHE:
            print(_('You have no external cache configured, so don\'t forget to restart your c3nav instance!'))
