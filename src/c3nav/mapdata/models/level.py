from decimal import Decimal
from itertools import chain
from operator import attrgetter

from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from shapely.ops import unary_union

from c3nav.mapdata.models.locations import SpecificLocation


class Level(SpecificLocation, models.Model):
    """
    A physical level of the map, containing building, spaces, doors…

    A level is a specific location, and can therefore be routed to and from, as well as belong to location groups.
    """
    new_serialize = True

    base_altitude = models.DecimalField(_('base altitude'), null=False, unique=True, max_digits=6, decimal_places=2)
    default_height = models.DecimalField(_('default space height'), max_digits=6, decimal_places=2, default=3.0,
                                         validators=[MinValueValidator(Decimal('0'))])
    door_height = models.DecimalField(_('door height'), max_digits=6, decimal_places=2, default=2.0,
                                      validators=[MinValueValidator(Decimal('0'))])
    on_top_of = models.ForeignKey('mapdata.Level', null=True, on_delete=models.CASCADE,
                                  related_name='levels_on_top', verbose_name=_('on top of'))
    short_label = models.SlugField(max_length=20, verbose_name=_('short label'), unique=True)

    class Meta:
        verbose_name = _('Level')
        verbose_name_plural = _('Levels')
        default_related_name = 'levels'
        ordering = ['base_altitude']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def lower(self, level_model=None):
        if self.on_top_of_id is not None:
            raise TypeError
        if level_model is None:
            level_model = Level
        return level_model.objects.filter(base_altitude__lt=self.base_altitude,
                                          on_top_of__isnull=True).order_by('-base_altitude')

    def higher(self, level_model=None):
        if self.on_top_of_id is not None:
            raise TypeError
        if level_model is None:
            level_model = Level
        return level_model.objects.filter(base_altitude__gt=self.base_altitude,
                                          on_top_of__isnull=True).order_by('base_altitude')

    @property
    def sublevels(self):
        if self.on_top_of is not None:
            raise TypeError
        return chain((self, ), self.levels_on_top.all())

    @property
    def sublevel_title(self):
        return '-' if self.on_top_of_id is None else self.title

    @property
    def primary_level(self):
        return self if self.on_top_of_id is None else self.on_top_of

    @property
    def primary_level_pk(self):
        return self.pk if self.on_top_of_id is None else self.on_top_of_id

    def details_display(self, editor_url=True, **kwargs):
        result = super().details_display(**kwargs)
        result['display'].insert(3, (_('short label'), self.short_label))
        result['display'].extend([
            (_('outside only'), self.base_altitude),
            (_('default height'), self.default_height),
        ])
        if editor_url:
            result['editor_url'] = reverse('editor.levels.detail', kwargs={'pk': self.pk})
        return result

    @cached_property
    def min_altitude(self):
        return min(self.altitudeareas.all(), key=attrgetter('altitude'), default=self.base_altitude).altitude

    @cached_property
    def bounds(self):
        return unary_union(tuple(item.geometry.buffer(0)
                                 for item in chain(self.altitudeareas.all(), self.buildings.all()))).bounds

    def get_icon(self):
        return super().get_icon() or 'layers'
