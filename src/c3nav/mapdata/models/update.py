import logging
import os
import pickle
import time
from contextlib import contextmanager, suppress, nullcontext
from functools import cached_property

from django.conf import settings
from django.core.cache import cache
from django.db import models, transaction, DatabaseError
from django.utils.http import int_to_base36
from django.utils.timezone import make_naive
from django.utils.translation import gettext_lazy as _
from shapely.ops import unary_union

from c3nav.mapdata.tasks import process_map_updates, delete_map_cache_key
from c3nav.mapdata.utils.cache.changes import GeometryChangeTracker
from c3nav.mapdata.utils.cache.local import per_request_cache
from c3nav.mapdata.utils.cache.types import MapUpdateTuple


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
    purge_all_cache = models.BooleanField(default=False, verbose_name=_("purge the entire cache"),
                                          help_text=_("This erases all map history when processed, meaning that all "
                                                      "tiles and renderings need to be re-rendered. Only use after "
                                                      "manually tampering with the database or to fix caching issues."))

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
    def last_update(cls, force=False) -> MapUpdateTuple:
        if not force:
            last_update = per_request_cache.get('mapdata:last_update', None)
            if last_update is not None:
                return last_update
        try:
            with cls.lock():
                last_update = cls.objects.latest().to_tuple
                per_request_cache.set('mapdata:last_update', last_update, None)
        except cls.DoesNotExist:
            last_update = (0, 0)
            per_request_cache.set('mapdata:last_update', last_update, None)
        return last_update

    @classmethod
    def last_processed_update(cls, force=False, lock=True) -> MapUpdateTuple:
        if not force:
            last_processed_update = per_request_cache.get('mapdata:last_processed_update', None)
            if last_processed_update is not None:
                return last_processed_update
        try:
            with (cls.lock() if lock else nullcontext()):
                last_processed_update = cls.objects.filter(processed=True).latest().to_tuple
                per_request_cache.set('mapdata:last_processed_update', last_processed_update, None)
        except cls.DoesNotExist:
            last_processed_update = (0, 0)
            per_request_cache.set('mapdata:last_processed_update', last_processed_update, None)
        return last_processed_update

    @classmethod
    def last_processed_geometry_update(cls, force=False) -> MapUpdateTuple:
        if not force:
            last_processed_geometry_update = per_request_cache.get('mapdata:last_processed_geometry_update', None)
            if last_processed_geometry_update is not None:
                return last_processed_geometry_update
        try:
            with cls.lock():
                last_processed_geometry_update = cls.objects.filter(processed=True,
                                                                    geometries_changed=True).latest().to_tuple
                per_request_cache.set('mapdata:last_processed_geometry_update', last_processed_geometry_update, None)
        except cls.DoesNotExist:
            last_processed_geometry_update = (0, 0)
            per_request_cache.set('mapdata:last_processed_geometry_update', last_processed_geometry_update, None)
        return last_processed_geometry_update

    @property
    def to_tuple(self) -> MapUpdateTuple:
        return self.pk, int(make_naive(self.datetime).timestamp())

    @property
    def cache_key(self):
        return self.build_cache_key(self.pk, int(make_naive(self.datetime).timestamp()))

    @classmethod
    def current_cache_key(cls):
        return cls.build_cache_key(*cls.last_update())

    @classmethod
    def current_processed_cache_key(cls):
        return cls.build_cache_key(*cls.last_processed_update())

    @classmethod
    def current_processed_geometry_cache_key(cls):
        return cls.build_cache_key(*cls.last_processed_geometry_update())

    @staticmethod
    def build_cache_key(pk: int, timestamp: int):
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

        cls.last_update()
        cls.last_processed_update()
        cls.last_processed_geometry_update()

        with cls.get_updates_to_process() as new_updates:
            prev_keys = (
                cls.current_processed_cache_key(),
                cls.current_processed_geometry_cache_key(),
            )

            # todo: we don't know how these get created, but this is how they get deleted! >:3
            from c3nav.mapdata.models.locations import LocationRedirect
            LocationRedirect.objects.filter(slug=None).delete()

            for key in prev_keys:
                transaction.on_commit(lambda: delete_map_cache_key.delay(cache_key=key))

            if not new_updates:
                return ()

            update_cache_key = MapUpdate.build_cache_key(*new_updates[-1].to_tuple)
            (settings.CACHE_ROOT / update_cache_key).mkdir(exist_ok=True)

            last_geometry_update = ([None] + [update for update in new_updates if update.geometries_changed])[-1]

            if last_geometry_update is not None:
                geometry_update_cache_key = MapUpdate.build_cache_key(*last_geometry_update.to_tuple)
                (settings.CACHE_ROOT / geometry_update_cache_key).mkdir(exist_ok=True)

                from c3nav.mapdata.utils.cache.changes import changed_geometries
                changed_geometries.reset()

                logger.info('Recalculating altitude areas...')

                from c3nav.mapdata.models import AltitudeArea
                AltitudeArea.recalculate()

                logger.info('%.3f m² of altitude areas affected.' % changed_geometries.area)

                last_processed_update = cls.last_processed_update(force=True, lock=False)

                purging_updates = [new_update.to_tuple for new_update in new_updates if new_update.purge_all_cache]
                num_purges = 0

                for new_update in new_updates:
                    logger.info('Applying changed geometries from MapUpdate #%(id)s (%(type)s)...' %
                                {'id': new_update.pk, 'type': new_update.type})
                    if new_update.purge_all_cache:
                        logger.info('Entire map purged by this update.')
                        changed_geometries.reset()
                        num_purges += 1
                    try:
                        new_changes = new_update.get_changed_geometries()

                        if new_changes is None:
                            logger.warning('changed_geometries pickle file not found.')
                        else:
                            if new_update.purge_all_cache:
                                # delete changed geometries of that update
                                new_changes.finalize()
                            elif num_purges < len(purging_updates):
                                # delete changed geometries of that update
                                new_changes.finalize()
                                logger.info('skipped %.3f m² affected by this update.' % new_changes.area)
                            else:
                                changed_geometries.combine(new_changes)
                                logger.info('%.3f m² affected by this update.' % new_changes.area)

                    except EOFError:
                        logger.warning('changed_geometries pickle file corrupted.')

                if purging_updates:
                    logger.info('Cache completely purged. After purge update,')
                logger.info('%.3f m² of geometries affected in total.' % changed_geometries.area)

                purge_levels = ()
                if purging_updates:
                    from c3nav.mapdata.models import Level
                    purge_levels = Level.objects.values_list("pk", flat=True)
                from c3nav.mapdata.models import Level
                changed_geometries.save(
                    default_update=purging_updates[-1] if purging_updates else last_processed_update,
                    new_update=new_updates[-1].to_tuple,
                    purge_levels=purge_levels,
                )

                logger.info('Rebuilding level render data...')

                from c3nav.mapdata.render.renderdata import LevelRenderData
                LevelRenderData.rebuild(geometry_update_cache_key)

                transaction.on_commit(
                    lambda: per_request_cache.set('mapdata:last_processed_geometry_update',
                                              last_geometry_update.to_tuple, None)
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

        old_cache_key = None
        if new:
            old_cache_key = self.current_cache_key()

        # todo: move this to some kind of processupdates stage
        from c3nav.mapdata.models.locations import LocationGroup, SpecificLocation
        LocationGroup.calculate_effective_order()
        SpecificLocation.calculate_effective_order()
        SpecificLocation.calculate_effective_icon()

        super().save(**kwargs)

        with suppress(FileExistsError):
            os.mkdir(os.path.dirname(self._changed_geometries_filename()))

        if self.geometries_changed:
            pickle.dump(changed_geometries, open(self._changed_geometries_filename(), 'wb'))

        if new:
            transaction.on_commit(lambda: delete_map_cache_key.delay(cache_key=old_cache_key))
            transaction.on_commit(
                lambda: per_request_cache.set('mapdata:last_update', self.to_tuple, None)
            )
            if settings.HAS_CELERY and settings.AUTO_PROCESS_UPDATES:
                transaction.on_commit(
                    lambda: process_map_updates.delay()
                )
