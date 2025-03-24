from django.core.cache import cache
from django.db import models
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from c3nav.mapdata.fields import I18nField
from c3nav.mapdata.models import MapUpdate


class TitledMixin(models.Model):
    title = I18nField(_('Title'), plural_name='titles', blank=True, fallback_any=True, fallback_value='{model} {pk}')
    titles: dict[str, str]

    class Meta:
        abstract = True

    @property
    def other_titles(self):
        return tuple(title for lang, title in self.titles.items() if lang != get_language())

    def __str__(self):
        return str(self.title)


class BoundsMixin(models.Model):
    bottom = models.DecimalField(_('bottom coordinate'), max_digits=6, decimal_places=2)
    left = models.DecimalField(_('left coordinate'), max_digits=6, decimal_places=2)
    top = models.DecimalField(_('top coordinate'), max_digits=6, decimal_places=2)
    right = models.DecimalField(_('right coordinate'), max_digits=6, decimal_places=2)

    class Meta:
        abstract = True

    @classmethod
    def max_bounds(cls):
        cache_key = 'mapdata:max_bounds:%s:%s' % (cls.__name__, MapUpdate.last_update().cache_key)
        result = cache.get(cache_key, None)
        if result is not None:
            return result
        from c3nav.mapdata.permissions import active_map_permissions
        with active_map_permissions.disable_access_checks():
            result = cls.objects.all().aggregate(models.Min('left'), models.Min('bottom'),
                                                 models.Max('right'), models.Max('top'))
            result = ((float(result['left__min'] or 0), float(result['bottom__min'] or 0)),
                      (float(result['right__max'] or 10), float(result['top__max'] or 10)))
        cache.set(cache_key, result, 900)
        return result

    @property
    def bounds(self):
        # noinspection PyTypeChecker
        return (float(self.left), float(self.bottom)), (float(self.right), float(self.top))
