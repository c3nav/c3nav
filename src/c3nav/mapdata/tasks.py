import logging
import time

from celery.exceptions import MaxRetriesExceededError
from django.contrib.auth import get_user_model
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


@app.task(bind=True, max_retries=10)
def update_ap_names_bssid_mapping(self, map_name, user_id):
    user = get_user_model().objects.filter(pk=user_id).first()
    if user is None:
        return
    from c3nav.mapdata.models.geometry.space import RangingBeacon
    todo = []
    for beacon in RangingBeacon.objects.filter(ap_name__in=map_name.keys(),
                                               beacon_type=RangingBeacon.BeaconType.EVENT_WIFI):
        print(beacon, "add ssids", set(map_name[beacon.ap_name]))
        if set(map_name[beacon.ap_name]) - set(beacon.addresses):
            todo.append((beacon, list(set(beacon.addresses) | set(map_name[beacon.ap_name]))))

    if todo:
        from c3nav.editor.models import ChangeSet
        from c3nav.editor.views.base import within_changeset
        changeset = ChangeSet()
        changeset.author = user
        with within_changeset(changeset=changeset, user=user) as locked_changeset:
            for beacon, addresses in todo:
                beacon.addresses = addresses
                beacon.save()
        with changeset.lock_to_edit() as locked_changeset:
            locked_changeset.title = 'passive update bssids'
            locked_changeset.apply(user)
