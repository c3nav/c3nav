from collections import OrderedDict

from django.core.cache import cache
from django.db import models
from django.db.models import Q
from django.utils.translation import get_language, get_language_info
from django.utils.translation import gettext_lazy as _

from c3nav.mapdata.fields import I18nField
from c3nav.mapdata.models import MapUpdate


class SerializableMixin(models.Model):
    _affected_by_changeset = None

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
        result = {}
        if include_type:
            result['type'] = self.__class__.__name__.lower()
        result['id'] = self.pk
        return result

    def details_display(self, **kwargs):
        return {
            'id': self.pk,
            'display': [
                (_('Type'), str(self.__class__._meta.verbose_name)),

            ],
            'display_extended': [
                (_('ID'), str(self.pk)),
            ]
        }

    def get_geometry(self, detailed_geometry=True):
        return None

    @property
    def title(self):
        return self._meta.verbose_name + ' ' + str(self.id)

    @classmethod
    def qs_for_request(cls, request, allow_none=False):
        return cls.objects.filter(cls.q_for_request(request, allow_none=allow_none))

    @classmethod
    def q_for_request(cls, *args, **kwargs):
        return Q()


class TitledMixin(SerializableMixin, models.Model):
    title = I18nField(_('Title'), plural_name='titles', blank=True, fallback_any=True, fallback_value='{model} {pk}')

    class Meta:
        abstract = True

    def serialize(self, **kwargs):
        result = super().serialize(**kwargs)
        return result

    def _serialize(self, detailed=True, **kwargs):
        result = super()._serialize(detailed=detailed, **kwargs)
        if detailed:
            result['titles'] = self.titles
        result['title'] = self.title
        return result

    @property
    def other_titles(self):
        return tuple(title for lang, title in self.titles.items() if lang != get_language())

    def details_display(self, **kwargs):
        result = super().details_display(**kwargs)
        for lang, title in sorted(self.titles.items(), key=lambda item: item[0] != get_language()):
            language = _('Title ({lang})').format(lang=get_language_info(lang)['name_translated'])
            result['display'].append((language, title))
        return result


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
        result = ((float(result['left__min'] or 0), float(result['bottom__min'] or 0)),
                  (float(result['right__max'] or 10), float(result['top__max'] or 10)))
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
