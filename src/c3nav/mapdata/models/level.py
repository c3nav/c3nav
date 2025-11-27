from decimal import Decimal
from itertools import chain
from operator import attrgetter
from typing import Optional, Never

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils.functional import cached_property
from django.utils.regex_helper import _lazy_re_compile
from django.utils.translation import gettext_lazy as _
from shapely.ops import unary_union

from c3nav.mapdata.models.access import AccessRestrictionMixin
from c3nav.mapdata.models.geometry.base import CachedBounds
from c3nav.mapdata.models.locations import LocationTagTargetMixin
from c3nav.mapdata.permissions import MapPermissionTaggedItem
from c3nav.mapdata.schemas.model_base import BoundsSchema
from c3nav.mapdata.utils.cache.proxied import versioned_per_request_cache

level_index_re = _lazy_re_compile(r"^[-a-zA-Z0-9._]+\Z")
validate_level_index = RegexValidator(
    level_index_re,
    # Translators: "letters" means latin letters: a-z and A-Z.
    _("Enter a valid “level index” consisting of letters, numbers, underscores, dots or hyphens."),
    "invalid",
)


class Level(LocationTagTargetMixin, AccessRestrictionMixin, models.Model):
    """
    A physical level of the map, containing building, spaces, doors…

    A level is a location target.
    """
    base_altitude = models.DecimalField(_('base altitude'), null=False, unique=True, max_digits=6, decimal_places=2)
    default_height = models.DecimalField(_('default space height'), max_digits=6, decimal_places=2, default=3.0,
                                         validators=[MinValueValidator(Decimal('0'))])
    door_height = models.DecimalField(_('door height'), max_digits=6, decimal_places=2, default=2.0,
                                      validators=[MinValueValidator(Decimal('0'))])
    on_top_of = models.ForeignKey('mapdata.Level', null=True, on_delete=models.CASCADE,
                                  related_name='levels_on_top', verbose_name=_('on top of'))
    intermediate = models.BooleanField(_("intermediate level"), default=False)
    short_label = models.CharField(max_length=20, verbose_name=_('short label'), unique=True,
                                   help_text=_('used for the level selector'))
    level_index = models.CharField(max_length=20, verbose_name=_('level index'), unique=True,
                                   validators=[validate_level_index], help_text=_('used for coordinates'))

    effective_bottom = models.DecimalField(_('bottom coordinate'),
                                           max_digits=6, decimal_places=2, editable=False, default=0)
    effective_left = models.DecimalField(_('left coordinate'),
                                         max_digits=6, decimal_places=2, editable=False, default=0)
    effective_top = models.DecimalField(_('top coordinate'),
                                        max_digits=6, decimal_places=2, editable=False, default=100)
    effective_right = models.DecimalField(_('right coordinate'),
                                          max_digits=6, decimal_places=2, editable=False, default=100)

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

    @property
    def primary_level_id(self):
        return self.pk if self.on_top_of_id is None else self.on_top_of_id

    @property
    def subtitle(self):
        return self.title

    def for_details_display(self):
        # todo: can we make this simpler or get rid of this?
        location = self.get_location()
        if location:
            return {
                'id': location.pk,
                'slug': location.effective_slug,
                'title': location.title,
                'can_search': location.can_search,
            }
        return self.title

    @cached_property
    def min_altitude(self):
        return min(self.altitudeareas.all(), key=attrgetter('altitude'), default=self.base_altitude).altitude

    @cached_property
    def level_id(self) -> int:
        return self.pk

    @classmethod
    def max_bounds(cls) -> tuple[tuple[float, float], tuple[float, float]]:
        # todo: calculate this as part of processupdates?
        cache_key = "mapdata:max_bounds:levels"
        from c3nav.mapdata.models import MapUpdate
        last_update = MapUpdate.last_update("mapdata.recalculate_level_bounds")
        result = versioned_per_request_cache.get(last_update, cache_key, None)  # todo: get correct update
        if result is not None:
            return result
        from c3nav.mapdata.permissions import active_map_permissions
        with active_map_permissions.disable_access_checks():
            result = cls.objects.all().aggregate(models.Min('effective_left'), models.Min('effective_bottom'),
                                                 models.Max('effective_right'), models.Max('effective_top'))
            result = ((float(result['effective_left__min'] or 0), float(result['effective_bottom__min'] or 0)),
                      (float(result['effective_right__max'] or 10), float(result['effective_top__max'] or 10)))
        versioned_per_request_cache.set(last_update, cache_key, result, 900)
        return result

    @classmethod
    def recalculate_bounds(cls):
        for level in cls.objects.prefetch_related("spaces", "buildings").all():
            level.effective_left, level.effective_bottom, level.effective_right, level.effective_top = unary_union(
                tuple(item.geometry.buffer(0) for item in chain(level.spaces.all(), level.buildings.all()))
            ).bounds
            level.save()

    @cached_property
    def bounds(self) -> Optional[BoundsSchema]:
        return {
            self.primary_level_id: ((self.effective_left, self.effective_bottom),
                                    (self.effective_right, self.effective_top))
        }

    @property
    def title(self):
        return _('Level %(short_label)s') % {"short_label": self.short_label}

    @property
    def cached_effective_geometries(self) -> list[Never]:
        return []

    @property
    def cached_points(self) -> list[Never]:
        return []

    @property
    def cached_bounds(self) -> CachedBounds:
        return CachedBounds(*(
            (MapPermissionTaggedItem(value=float(value), access_restrictions=self.effective_access_restrictions), )
            for value in (self.effective_left, self.effective_bottom, self.effective_right, self.effective_top)
        ))
