import pickle
from contextlib import contextmanager

from django.conf import settings
from django.core.cache import cache
from django.db import models, transaction
from django.utils.http import int_to_base36
from django.utils.timezone import make_naive
from django.utils.translation import ugettext_lazy as _


class MapUpdate(models.Model):
    """
    A map update. created whenever mapdata is changed.
    """
    datetime = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    type = models.CharField(max_length=32)
    processed = models.BooleanField(default=False)
    changed_geometries = models.BinaryField(null=True)

    class Meta:
        verbose_name = _('Map update')
        verbose_name_plural = _('Map updates')
        default_related_name = 'mapupdates'
        get_latest_by = 'datetime'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.was_processed = self.processed

    @classmethod
    def last_update(cls):
        last_update = cache.get('mapdata:last_update', None)
        if last_update is not None:
            return last_update
        with cls.lock():
            last_update = cls.objects.latest()
            result = last_update.to_tuple
            cache.set('mapdata:last_update', result, 900)
        return result

    @classmethod
    def last_processed_update(cls):
        last_processed_update = cache.get('mapdata:last_processed_update', None)
        if last_processed_update is not None:
            return last_processed_update
        with cls.lock():
            last_processed_update = cls.objects.filter(processed=True).latest()
            result = last_processed_update.to_tuple
            cache.set('mapdata:last_processed_update', result, 900)
        return result

    @property
    def to_tuple(self):
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

    @staticmethod
    def build_cache_key(pk, timestamp):
        return int_to_base36(pk)+'_'+int_to_base36(timestamp)

    @classmethod
    @contextmanager
    def lock(cls):
        with transaction.atomic():
            yield cls.objects.select_for_update().earliest()

    @classmethod
    def process_updates(cls):
        with cls.lock():
            new_updates = tuple(cls.objects.filter(processed=False))
            if not new_updates:
                return ()

            from c3nav.mapdata.models import AltitudeArea
            AltitudeArea.recalculate()

            from c3nav.mapdata.render.data import LevelRenderData
            LevelRenderData.rebuild()

            last_unprocessed_update = cls.objects.filter(processed=False).latest().to_tuple
            for new_update in new_updates:
                pickle.loads(new_update.changed_geometries).save(last_unprocessed_update, new_update.to_tuple)
                new_update.processed = True
                new_update.save()

            cache.set('mapdata:last_processed_update', new_updates[-1].to_tuple, 900)

            return new_updates

    def save(self, **kwargs):
        if self.pk is not None and (self.was_processed or not self.processed):
            raise TypeError

        from c3nav.mapdata.cache import changed_geometries
        self.changed_geometries = pickle.dumps(changed_geometries)

        super().save(**kwargs)

        cache.set('mapdata:last_update', self.to_tuple, 900)
