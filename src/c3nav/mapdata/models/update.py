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
from django.db.models.constraints import UniqueConstraint
from django.db.models.expressions import Exists, OuterRef
from django.db.models.query_utils import Q
from django.utils import timezone
from django.utils.http import int_to_base36
from django.utils.timezone import make_naive
from django.utils.translation import gettext_lazy as _
from shapely.ops import unary_union

from c3nav.mapdata.tasks import process_map_updates, delete_map_cache_key
from c3nav.mapdata.utils.cache.changes import GeometryChangeTracker
from c3nav.mapdata.utils.cache.local import per_request_cache
from c3nav.mapdata.utils.cache.types import MapUpdateTuple


class MapUpdateJobType(models.TextChoices):
    LOCATION_META = "locations-meta", _("generate location metadata")
    ALTITUDE_AREAS = "altitudeareas", _("recalculate altitude areas")
    RENDERDATA = "renderdata", _("generate render data")
    ROUTER = "router", _("generate router")
    LOCATOR = "locator", _("generate locator")


class MapUpdateJobStatus(models.IntegerChoices):
    RUNNING = 0, _("running")
    FAILED = 1, _("failed")
    TIMEOUT = 2, _("timeout")
    SUCCESS = 3, _("success")


class MapUpdateJob(models.Model):
    mapupdate = models.ForeignKey("MapUpdate", on_delete=models.CASCADE, related_name="jobs")
    job_type = models.CharField(max_length=16, choices=MapUpdateJobType.choices, db_index=True)
    status = models.PositiveSmallIntegerField(choices=MapUpdateJobStatus.choices, db_index=True)
    start = models.DateTimeField(auto_now_add=True)
    end = models.DateTimeField(null=True)

    class Meta:
        verbose_name = _('Map update job')
        verbose_name_plural = _('Map update jobs')
        constraints = [
            UniqueConstraint(
                fields=("mapupdate", "job_type"),
                condition=Q(status__in=(MapUpdateJobStatus.RUNNING, MapUpdateJobStatus.FAILED)),
                name="no_duplicate_jobs_unless_failed"
            )
        ]
        get_latest_by = ("end", "start")

    @classmethod
    @contextmanager
    def lock(cls, job_type: MapUpdateJobType):
        with transaction.atomic():
            try:
                first = cls.objects.filter(job_type=job_type).order_by("pk").first()
            except cls.DoesNotExist:
                try:
                    first = cls.objects.order_by("pk").first()
                except cls.DoesNotExist:
                    yield
            yield cls.objects.select_for_update().get(pk=first.pk)

    @classmethod
    def last_successful_update(cls, job_type: MapUpdateJobType | str, *, nocache: bool = False,
                               geometry_only = False) -> MapUpdateTuple:
        cache_key = f"mapdata:last_job:{job_type}:{geometry_only}:update"
        if not nocache:
            last_update = per_request_cache.get(cache_key, None)
            if last_update is not None:
                return last_update
        try:
            with cls.lock(job_type):
                last_finished_job = MapUpdateJob.objects.filter(
                    job_type=MapUpdateJobType.LOCATOR,
                    status=MapUpdateJobStatus.SUCCESS,
                    **({"mapupdate__geometries_changed": True} if geometry_only else {}),
                ).select_related("mapupdate").latest()
                last_processed_update = last_finished_job.mapupdate.to_tuple
                per_request_cache.set(cache_key, last_processed_update, None)
        except MapUpdateJob.DoesNotExist:
            last_processed_update = (0, 0)
            per_request_cache.set(cache_key, last_processed_update, None)
        return last_processed_update

    def mark_success(self):
        self.status = MapUpdateJobStatus.SUCCESS
        self.end = timezone.now()
        self.save()

        last_geometry_update = MapUpdate.objects.filter(pk__lte=self.mapupdate_id, geometries_changed=True).latest()
        transaction.on_commit(
            lambda: per_request_cache.set(f"mapdata:last_job:{self.job_type}:{False}:update",
                                          self.mapupdate.to_tuple, None)
        )
        transaction.on_commit(
            lambda: per_request_cache.set(f"mapdata:last_job:{self.job_type}:{True}:update",
                                          last_geometry_update, None)
        )


class MapUpdateQuerySet(models.QuerySet):
    def with_all_jobs_success(self):
        return self.with_job_success(MapUpdateJobType.LOCATOR)

    def with_job_success(self, job_type: MapUpdateJobType):
        return self.with_job(
            job_type=job_type,
            status=MapUpdateJobStatus.SUCCESS,
        )

    def with_job(self, **kwargs):
        return self.filter(Exists(MapUpdateJob.objects.filter(
            mapupdate=OuterRef("pk"),
            **kwargs,
        )))

    def without_all_jobs_success(self):
        return self.without_job_success(MapUpdateJobType.LOCATOR)

    def without_job_success(self, job_type: MapUpdateJobType):
        return self.without_job(
            job_type=job_type,
            status=MapUpdateJobStatus.SUCCESS,
        )

    def without_job(self, **kwargs):
        return self.exclude(Exists(MapUpdateJob.objects.filter(
            mapupdate=OuterRef("pk"),
            **kwargs,
        )))


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
    geometries_changed = models.BooleanField()

    objects = models.Manager.from_queryset(MapUpdateQuerySet)()

    class Meta:
        verbose_name = _('Map update')
        verbose_name_plural = _('Map updates')
        default_related_name = 'mapupdates'
        ordering = ('datetime', )
        get_latest_by = 'datetime'

    @classmethod
    def last_update(cls, force=False) -> MapUpdateTuple:
        if not force:
            last_update = per_request_cache.get('mapdata:last_update', None)
            if last_update is not None:
                return last_update
        try:
            with cls.creation_lock():
                last_update = cls.objects.latest().to_tuple
                per_request_cache.set('mapdata:last_update', last_update, None)
        except cls.DoesNotExist:
            last_update = (0, 0)
            per_request_cache.set('mapdata:last_update', last_update, None)
        return last_update

    @classmethod
    def last_processed_update(cls, force=False) -> MapUpdateTuple:
        return MapUpdateJob.last_successful_update(MapUpdateJobType.LOCATOR, nocache=force)

    @classmethod
    def last_processed_geometry_update(cls, force=False) -> MapUpdateTuple:
        return MapUpdateJob.last_successful_update(MapUpdateJobType.LOCATOR, geometry_only=True, nocache=force)

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
    def creation_lock(cls):
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
        try:
            last_processed_update: MapUpdateTuple = cls.last_processed_update()
        except MapUpdateJob.DoesNotExist:
            queryset = cls.objects.all()
        else:
            queryset = cls.objects.filter(pk__gt=last_processed_update[0])

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
            new_updates: tuple[MapUpdate]

            prev_keys = (
                cls.current_processed_cache_key(),
                cls.current_processed_geometry_cache_key(),
            )

            for key in prev_keys:
                # todo: eventually get ridof/move this
                transaction.on_commit(lambda: delete_map_cache_key.delay(cache_key=key))

            if not new_updates:
                return ()

            jobs = []
            for job_type in (MapUpdateJobType.LOCATION_META,
                             MapUpdateJobType.ALTITUDE_AREAS,
                             MapUpdateJobType.RENDERDATA,
                             MapUpdateJobType.ROUTER,
                             MapUpdateJobType.LOCATOR):
                jobs.append(new_updates[-1].jobs.create(
                    job_type=job_type,
                    status=MapUpdateJobStatus.RUNNING,
                ))

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

                last_processed_update = cls.last_processed_update(force=True)

                for new_update in new_updates:
                    logger.info('Applying changed geometries from MapUpdate #%(id)s (%(type)s)...' %
                                {'id': new_update.pk, 'type': new_update.type})
                    try:
                        new_changes = new_update.get_changed_geometries()
                        if new_changes is None:
                            logger.warning('changed_geometries pickle file not found.')
                        else:
                            logger.info('%.3f m² affected by this update.' % new_changes.area)
                            changed_geometries.combine(new_changes)
                    except EOFError:
                        logger.warning('changed_geometries pickle file corrupted.')

                logger.info('%.3f m² of geometries affected in total.' % changed_geometries.area)

                changed_geometries.save(last_processed_update, new_updates[-1].to_tuple)

                logger.info('Rebuilding level render data...')

                from c3nav.mapdata.render.renderdata import LevelRenderData
                LevelRenderData.rebuild(geometry_update_cache_key)
            else:
                logger.info('No geometries affected.')

            logger.info('Rebuilding router...')
            from c3nav.routing.router import Router
            router = Router.rebuild(new_updates[-1].to_tuple)

            logger.info('Rebuilding locator...')
            from c3nav.routing.locator import Locator
            Locator.rebuild(new_updates[-1].to_tuple, router)

            for job in jobs:
                job.mark_success()

            return new_updates

    def save(self, **kwargs):
        new = self.pk is None
        if not new:
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
            # todo: eventually get rid of this
            transaction.on_commit(lambda: delete_map_cache_key.delay(cache_key=old_cache_key))
            transaction.on_commit(
                lambda: per_request_cache.set('mapdata:last_update', self.to_tuple, None)
            )
            if settings.HAS_CELERY and settings.AUTO_PROCESS_UPDATES:
                transaction.on_commit(
                    lambda: process_map_updates.delay()
                )
