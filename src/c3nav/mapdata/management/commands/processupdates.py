import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import DatabaseError
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.tasks import process_map_updates


class Command(BaseCommand):
    help = 'process unprocessed map updates'

    def handle(self, *args, **options):
        logger = logging.getLogger('c3nav')

        try:
            process_map_updates()
        except DatabaseError:
            logger.error(_('There is already map update processing in progress.'))

        if not settings.HAS_REAL_CACHE:
            print(_('You have no external cache configured, so don\'t forget to restart your c3nav instance!'))
