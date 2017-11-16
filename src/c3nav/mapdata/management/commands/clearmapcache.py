import logging
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.translation import ugettext_lazy as _


class Command(BaseCommand):
    help = 'clear the mapdata cache'

    def add_arguments(self, parser):
        parser.add_argument('--include-history', action='store_const', const=True, default=False,
                            help=_('incluce all history as well'))

    def handle(self, *args, **options):
        from c3nav.mapdata.models import MapUpdate

        logger = logging.getLogger('c3nav')

        MapUpdate.objects.create(type='management')
        logger.info('New management update created.')

        if options['include_history']:
            logger.info('Deleting base history...')
            for filename in os.listdir(settings.CACHE_ROOT):
                if filename.startswith('level_') and '_history_' in filename:
                    logger.info('Deleting %s...' % filename)
                    os.remove(os.path.join(settings.CACHE_ROOT, filename))
            logger.info('Base history deleted.')

        if not settings.HAS_REAL_CACHE:
            print(_('You have no external cache configured, so don\'t forget to restart your c3nav instance!'))

        if not settings.HAS_CELERY:
            print(_('You don\'t have celery installed, so don\'t forget to call processupdates!'))
