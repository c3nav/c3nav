import logging
import time

from celery.exceptions import MaxRetriesExceededError
from django.core.cache import cache
from django.utils.formats import date_format
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from c3nav.celery import app

logger = logging.getLogger('c3nav')


@app.task(bind=True, max_retries=10)
def process_map_updates(self):
    if self.request.called_directly:
        logger.info('Processing map updates by direct command...')
    else:
        logger.info('Processing map updates...')

    from c3nav.mapdata.models import MapUpdate
    try:
        try:
            updates = MapUpdate.process_updates()
        except MapUpdate.ProcessUpdatesAlreadyRunning:
            if self.request.called_directly:
                raise
            logger.info('Processing is already running, retrying in 30 seconds.')
            raise self.retry(countdown=30)
        except Exception:
            cache.set('mapdata:last_process_updates_run', (int(time.time()), False), None)
            raise
        else:
            cache.set('mapdata:last_process_updates_run', (int(time.time()), True), None)
    except MaxRetriesExceededError:
        logger.info('Cannot retry, retries exceeded. Exiting.')
        return

    if updates:
        print()

    logger.info(ngettext_lazy('%d map update processed.', '%d map updates processed.', len(updates)) % len(updates))

    if updates:
        logger.info(_('Last processed update: %(date)s (#%(id)d)') % {
            'date': date_format(updates[-1].datetime, 'DATETIME_FORMAT'),
            'id': updates[-1].pk,
        })


@app.task(bind=True, max_retries=10)
def delete_map_cache_key(self, cache_key):
    if hasattr(cache, 'keys'):
        for key in cache.keys(f'*{cache_key}*'):
            cache.delete(key)
