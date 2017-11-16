import logging

from django.db import DatabaseError
from django.utils.formats import date_format
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext_lazy

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
        updates = MapUpdate.process_updates()
    except DatabaseError:
        if self.request.called_directly:
            raise
        logger.info('Processing is already running, retrying in 30 seconds.')
        raise self.retry(countdown=30)

    if updates:
        print()

    logger.info(ungettext_lazy('%d map update processed.', '%d map updates processed.', len(updates)) % len(updates))

    if updates:
        logger.info(_('Last processed update: %(date)s (#%(id)d)') % {
            'date': date_format(updates[-1].datetime, 'DATETIME_FORMAT'),
            'id': updates[-1].pk,
        })
