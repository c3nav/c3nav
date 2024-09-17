import logging
import os
import pickle
import time
from contextlib import contextmanager, suppress
from functools import cached_property
from sqlite3 import DatabaseError

from django.conf import settings
from django.core.cache import cache
from django.db import models, transaction
from django.utils.http import int_to_base36
from django.utils.timezone import make_naive
from django.utils.translation import gettext_lazy as _
from shapely.ops import unary_union

from c3nav.mapdata.tasks import process_map_updates
from c3nav.mapdata.utils.cache.changes import GeometryChangeTracker


class MapUpdate(models.Model):
    """
    A map update. created whenever mapdata is changed.
    """
    TYPES = (
        ('changeset', _('changeset applied')),
        ('direct_edit', _('direct edit')),
        ('control_panel', _('via control panel')),
        ('management', 'manage.py clearmapcache'),
    )
    datetime = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    type = models.CharField(max_length=32, choices=TYPES)
    processed = models.BooleanField(default=False)
    geometries_changed = models.BooleanField()

    class Meta:
        verbose_name = _('Map update')
        verbose_name_plural = _('Map updates')
        default_related_name = 'mapupdates'
        ordering = ('datetime', )
        get_latest_by = 'datetime'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.was_processed = self.processed

    @classmethod
    def last_update(cls, force=False):
        if not force:
            last_update = cache.get('mapdata:last_update', None)
            if last_update is not None:
                return last_update
        try:
            with cls.lock():
                last_update = cls.objects.latest().to_tuple
                cache.set('mapdata:last_update', last_update, None)
        except cls.DoesNotExist:
            last_update = (0, 0)
            cache.set('mapdata:last_update', last_update, None)
        return last_update

    @classmethod
    def last_processed_update(cls, force=False):
        if not force:
            last_processed_update = cache.get('mapdata:last_processed_update', None)
            if last_processed_update is not None:
                return last_processed_update
        try:
            with cls.lock():
                last_processed_update = cls.objects.filter(processed=True).latest().to_tuple
                cache.set('mapdata:last_processed_update', last_processed_update, None)
        except cls.DoesNotExist:
            last_processed_update = (0, 0)
            cache.set('mapdata:last_processed_update', last_processed_update, None)
        return last_processed_update

    @classmethod
    def last_processed_geometry_update(cls, force=False):
        if not force:
            last_processed_geometry_update = cache.get('mapdata:last_processed_geometry_update', None)
            if last_processed_geometry_update is not None:
                return last_processed_geometry_update
        try:
            with cls.lock():
                last_processed_geometry_update = cls.objects.filter(processed=True,
                                                                    geometries_changed=True).latest().to_tuple
                cache.set('mapdata:last_processed_geometry_update', last_processed_geometry_update, None)
        except cls.DoesNotExist:
            last_processed_geometry_update = (0, 0)
            cache.set('mapdata:last_processed_geometry_update', last_processed_geometry_update, None)
        return last_processed_geometry_update

    @property
    def to_tuple(self):
        return self.pk, int(make_naive(self.datetime).timestamp())

    @property
    def cache_key(self):
        return self.build_cache_key(self.pk, int(make_naive(self.datetime).timestamp()))

    @classmethod
    def current_cache_key(cls, request=None):
        return cls.build_cache_key(*cls.last_update())

    @classmethod
    def current_processed_cache_key(cls, request=None):
        return cls.build_cache_key(*cls.last_processed_update())

    @classmethod
    def current_processed_geometry_cache_key(cls, request=None):
        return cls.build_cache_key(*cls.last_processed_geometry_update())

    @staticmethod
    def build_cache_key(pk, timestamp):
        return int_to_base36(pk)+'_'+int_to_base36(timestamp)

    @classmethod
    @contextmanager
    def lock(cls):
        with transaction.atomic():
            try:
                earliest = cls.objects.earliest()
            except cls.DoesNotExist:
                yield
            else:
                yield cls.objects.select_for_update().get(pk=earliest.pk)

    def _changed_geometries_filename(self):
        return settings.CACHE_ROOT / 'changed_geometries' / ('update_%d.pickle' % self.pk)

    def get_changed_geometries(self) -> GeometryChangeTracker | None:
        try:
            return pickle.load(open(self._changed_geometries_filename(), 'rb'))
        except FileNotFoundError:
            return None

    @cached_property
    def changed_geometries_summary(self):
        if self.pk is None:
            return None
        cache_key = f"mapdata:changed_geometries_summary:{self.pk}"
        result = cache.get(cache_key, None)
        if result is None:
            changes = self.get_changed_geometries()
            if changes is None:
                return None
            from c3nav.mapdata.models import Level
            level_titles = dict(Level.objects.all().values_list('pk', 'short_label'))
            result = {
                "area": changes.area,
                "area_by_level": [
                    {
                        "level": level_titles.get(level_id, f"(unknown level #{level_id}"),
                        "area": unary_union(geometries).area,
                    } for level_id, geometries in changes._geometries_by_level.items()
                ]
            }
            cache.set(cache_key, result, 86400)
        return result

    class ProcessUpdatesAlreadyRunning(Exception):
        pass

    @classmethod
    @contextmanager
    def get_updates_to_process(cls):
        queryset = cls.objects.filter(processed=False)
        with transaction.atomic():
            if settings.HAS_REDIS:
                import redis
                lock_aquired = None
                client = redis.Redis(connection_pool=settings.REDIS_CONNECTION_POOL)
                lock = client.lock('mapupdate:process_updates:lock', timeout=1800)
                try:
                    lock_aquired = lock.acquire(blocking=False)
                    if not lock_aquired:
                        raise cls.ProcessUpdatesAlreadyRunning
                    cache.set('mapdata:last_process_updates_start', int(time.time()), None)
                    yield tuple(queryset)
                finally:
                    if lock_aquired:
                        lock.release()
            else:
                try:
                    yield tuple(queryset.select_for_update(nowait=True))
                except DatabaseError:
                    raise cls.ProcessUpdatesAlreadyRunning

    @classmethod
    def process_updates(cls):
        logger = logging.getLogger('c3nav')

        with cls.get_updates_to_process() as new_updates:
            if not new_updates:
                return ()

            update_cache_key = MapUpdate.build_cache_key(*new_updates[-1].to_tuple)
            (settings.CACHE_ROOT / update_cache_key).mkdir()

            last_geometry_update = ([None] + [update for update in new_updates if update.geometries_changed])[-1]

            if last_geometry_update is not None:
                geometry_update_cache_key = MapUpdate.build_cache_key(*last_geometry_update.to_tuple)

                from c3nav.mapdata.utils.cache.changes import changed_geometries
                changed_geometries.reset()

                logger.info('Recalculating altitude areas...')

                from c3nav.mapdata.models import AltitudeArea
                AltitudeArea.recalculate()

                logger.info('%.3f m² of altitude areas affected.' % changed_geometries.area)

                last_processed_update = cls.last_processed_update(force=True)

                for new_update in new_updates:
                    logger.info('Applying changed geometries from MapUpdate #%(id)s (%(type)s)...' %
                                {'id': new_update.pk, 'type': new_update.type})
                    new_changes = new_update.get_changed_geometries()
                    if new_changes is None:
                        logger.warning('changed_geometries pickle file not found.')
                    else:
                        logger.info('%.3f m² affected by this update.' % new_changes.area)
                        changed_geometries.combine(new_changes)

                logger.info('%.3f m² of geometries affected in total.' % changed_geometries.area)

                changed_geometries.save(last_processed_update, new_updates[-1].to_tuple)

                logger.info('Rebuilding level render data...')

                from c3nav.mapdata.render.renderdata import LevelRenderData
                LevelRenderData.rebuild(geometry_update_cache_key)

                transaction.on_commit(
                    lambda: cache.set('mapdata:last_processed_geometries_update', last_geometry_update.to_tuple, None)
                )
            else:
                logger.info('No geometries affected.')

            logger.info('Rebuilding router...')
            from c3nav.routing.router import Router
            router = Router.rebuild(new_updates[-1].to_tuple)

            logger.info('Rebuilding locator...')
            from c3nav.routing.locator import Locator
            Locator.rebuild(new_updates[-1].to_tuple, router)

            for new_update in reversed(new_updates):
                new_update.processed = True
                new_update.save()

            transaction.on_commit(
                lambda: cache.set('mapdata:last_processed_update', new_updates[-1].to_tuple, None)
            )

            return new_updates

    def save(self, **kwargs):
        new = self.pk is None
        if not new and (self.was_processed or not self.processed):
            raise TypeError

        from c3nav.mapdata.utils.cache.changes import changed_geometries

        if self.geometries_changed is None:
            self.geometries_changed = not changed_geometries.is_empty

        super().save(**kwargs)

        with suppress(FileExistsError):
            os.mkdir(os.path.dirname(self._changed_geometries_filename()))

        if self.geometries_changed:
            pickle.dump(changed_geometries, open(self._changed_geometries_filename(), 'wb'))

        if new:
            transaction.on_commit(
                lambda: cache.set('mapdata:last_update', self.to_tuple, None)
            )
            if settings.HAS_CELERY and settings.AUTO_PROCESS_UPDATES:
                transaction.on_commit(
                    lambda: process_map_updates.delay()
                )
