import logging
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import DatabaseError
from django.utils.translation import gettext_lazy as _

from c3nav.mapdata.tasks import process_map_updates


class Command(BaseCommand):
    help = 'clear the mapdata cache'

    def add_arguments(self, parser):
        parser.add_argument('--include-history', action='store_const', const=True, default=False,
                            help=_('incluce all history as well'))
        parser.add_argument('--include-geometries', action='store_const', const=True, default=False,
                            help=_('incluce all geometries as well'))
        parser.add_argument('--no-process', action='store_const', const=True, default=False,
                            help=_('don\'t run processupdates if celery is not setup'))

    def handle(self, *args, **options):
        from c3nav.mapdata.models import MapUpdate

        logger = logging.getLogger('c3nav')

        MapUpdate.objects.create(type='management', geometries_changed=options['include_geometries'],
                                 purge_all_cache=options['include_history'])
        logger.info('New management update created.')

        if not settings.HAS_CELERY and not options['no_process']:
            print(_('You don\'t have celery installed, so we will run processupdates now...'))
            process_map_updates()

        if not settings.HAS_REAL_CACHE:
            print(_('You have no external cache configured, so don\'t forget to restart your c3nav instance!'))
