import os
import pickle
from contextlib import contextmanager, suppress
from functools import cached_property

from django.conf import settings
from django.core.cache import cache
from django.db import models, transaction
from django.db.models.constraints import UniqueConstraint
from django.db.models.query_utils import Q
from django.utils import timezone
from django.utils.http import int_to_base36
from django.utils.timezone import make_naive
from django.utils.translation import gettext_lazy as _
from shapely.ops import unary_union

from c3nav.mapdata.tasks import delete_map_cache_key, schedule_available_mapupdate_jobs
from c3nav.mapdata.updatejobs import update_job_configs, run_eager_mapupdate_jobs
from c3nav.mapdata.utils.cache.changes import GeometryChangeTracker
from c3nav.mapdata.utils.cache.local import per_request_cache
from c3nav.mapdata.utils.cache.types import MapUpdateTuple


class MapUpdateJobStatus(models.IntegerChoices):
    RUNNING = 0, _("running")
    FAILED = 1, _("failed")
    TIMEOUT = 2, _("timeout")
    SKIPPED = 3, _("not needed")
    SUCCESS = 4, _("success")


MAPUPDATE_JOB_TYPES = ((key, job_config.title) for key, job_config in update_job_configs.items())


class MapUpdateJob(models.Model):
    mapupdate = models.ForeignKey("MapUpdate", on_delete=models.CASCADE, related_name="jobs")
    job_type = models.CharField(max_length=64, choices=MAPUPDATE_JOB_TYPES, db_index=True)
    status = models.PositiveSmallIntegerField(choices=MapUpdateJobStatus.choices, db_index=True)
    start = models.DateTimeField(auto_now_add=True)
    end = models.DateTimeField(null=True)

    class Meta:
        verbose_name = _('Map update job')
        verbose_name_plural = _('Map update jobs')
        constraints = [
            UniqueConstraint(
                fields=("job_type", ),
                condition=Q(status=MapUpdateJobStatus.RUNNING),
                name="only_one_job_per_type_running"
            ),
            UniqueConstraint(
                fields=("mapupdate", "job_type"),
                condition=Q(status__in=(MapUpdateJobStatus.RUNNING,
                                        MapUpdateJobStatus.SKIPPED,
                                        MapUpdateJobStatus.SUCCESS)),
                name="no_duplicate_jobs_per_update_unless_failed"
            )
        ]
        get_latest_by = ("end", "start")

    @classmethod
    @contextmanager
    def lock(cls, job_type: str):
        if job_type not in update_job_configs:
            raise ValueError(f'Uknown job type: {job_type}')
        with transaction.atomic():
            first = cls.objects.filter(job_type=job_type).order_by("pk").first()
            if first is None:
                first = cls.objects.order_by("pk").first()
            if first is None:
                yield
            yield cls.objects.select_for_update().get(pk=first.pk)

    @classmethod
    def _last_update_with_state(cls, job_type: str, states: set[MapUpdateJobStatus]) -> MapUpdateTuple:
        if job_type not in update_job_configs:
            raise ValueError(f'Uknown job type: {job_type}')
        try:
            with cls.lock(job_type):
                last_finished_job = MapUpdateJob.objects.filter(
                    job_type=job_type,
                    status__in=states,
                ).select_related("mapupdate").latest()
                return last_finished_job.mapupdate.to_tuple
        except MapUpdateJob.DoesNotExist:
            return MapUpdateTuple(mapupdate_id=0, timestamp=0)

    @classmethod
    def last_successful_or_skipped_update(cls, job_type: str) -> MapUpdateTuple:
        return cls._last_update_with_state(job_type, {MapUpdateJobStatus.SUCCESS, MapUpdateJobStatus.SKIPPED})

    @classmethod
    def last_successful_update(cls, job_type: str, *, nocache: bool = False) -> MapUpdateTuple:
        if job_type not in update_job_configs:
            raise ValueError(f'Uknown job type: {job_type}')
        cache_key = f"mapdata:last_job:{job_type}:update"
        if not nocache:
            last_update = per_request_cache.get(cache_key, None)
            if last_update is not None:
                return last_update

        last_successful_update = cls._last_update_with_state(job_type, {MapUpdateJobStatus.SUCCESS})
        per_request_cache.set(cache_key, last_successful_update, None)
        return last_successful_update

    def update_status(self, status: MapUpdateJobStatus):
        if self.status != MapUpdateJobStatus.RUNNING:
            raise ValueError
        self.status = status
        self.end = timezone.now()
        self.save()
        if status == MapUpdateJobStatus.SUCCESS:
            transaction.on_commit(
                lambda: per_request_cache.set(f"mapdata:last_successful_job:{self.job_type}:update",
                                              self.mapupdate.to_tuple, None)
            )


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
            last_update = MapUpdateTuple(mapupdate_id=0, timestamp=0)
            per_request_cache.set('mapdata:last_update', last_update, None)
        return last_update

    @property
    def to_tuple(self) -> MapUpdateTuple:
        return MapUpdateTuple(mapupdate_id=self.pk, timestamp=int(make_naive(self.datetime).timestamp()))

    @classmethod
    def current_cache_key(cls) -> str:
        # todo: need to get rid of this
        return cls.last_update().cache_key

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
                    lambda: schedule_available_mapupdate_jobs.delay()
                )
            else:
                run_eager_mapupdate_jobs(self)
