from collections import OrderedDict

from django.core.cache import cache
from django.db import models
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import get_language

from c3nav.mapdata.fields import JSONField
from c3nav.mapdata.models import MapUpdate


class SerializableMixin(models.Model):
    class Meta:
        abstract = True

    def serialize(self, **kwargs):
        return self._serialize(**kwargs)

    @classmethod
    def serialize_type(cls, **kwargs):
        return OrderedDict((
            ('name', cls.__name__.lower()),
            ('name_plural', cls._meta.default_related_name),
            ('title', str(cls._meta.verbose_name)),
            ('title_plural', str(cls._meta.verbose_name_plural)),
        ))

    def _serialize(self, include_type=False, **kwargs):
        result = OrderedDict()
        if include_type:
            result['type'] = self.__class__.__name__.lower()
        result['id'] = self.pk
        return result

    @property
    def title(self):
        return self._meta.verbose_name + ' ' + str(self.id)


class TitledMixin(SerializableMixin, models.Model):
    titles = JSONField(default={})

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.titles = self.titles.copy()

    def serialize(self, **kwargs):
        result = super().serialize(**kwargs)
        return result

    def _serialize(self, **kwargs):
        result = super()._serialize(**kwargs)
        result['titles'] = self.titles
        result['title'] = self.title
        return result

    @property
    def title(self):
        lang = get_language()
        if self.titles:
            if lang in self.titles:
                return self.titles[lang]
            return next(iter(self.titles.values()))
        return super().title


class BoundsMixin(SerializableMixin, models.Model):
    bottom = models.DecimalField(_('bottom coordinate'), max_digits=6, decimal_places=2)
    left = models.DecimalField(_('left coordinate'), max_digits=6, decimal_places=2)
    top = models.DecimalField(_('top coordinate'), max_digits=6, decimal_places=2)
    right = models.DecimalField(_('right coordinate'), max_digits=6, decimal_places=2)

    class Meta:
        abstract = True

    @classmethod
    def max_bounds(cls):
        cache_key = 'mapdata:max_bounds:%s:%s' % (cls.__name__, MapUpdate.current_cache_key())
        result = cache.get(cache_key, None)
        if result is not None:
            return result
        result = cls.objects.all().aggregate(models.Min('left'), models.Min('bottom'),
                                             models.Max('right'), models.Max('top'))
        result = ((float(result['left__min']), float(result['bottom__min'])),
                  (float(result['right__max']), float(result['top__max'])))
        cache.set(cache_key, result, 900)
        return result

    def _serialize(self, level=True, **kwargs):
        result = super()._serialize(**kwargs)
        result['bounds'] = self.bounds
        return result

    @property
    def bounds(self):
        # noinspection PyTypeChecker
        return (float(self.left), float(self.bottom)), (float(self.right), float(self.top))
