import operator
import string
from datetime import timedelta
from decimal import Decimal
from functools import reduce
from itertools import chain
from operator import attrgetter
from typing import TYPE_CHECKING, Optional, TypeAlias, Union, Iterable

from django.conf import settings
from django.core.cache import cache
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.functional import cached_property
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _, get_language, get_language_info
from django.utils.translation import ngettext_lazy
from shapely import Point

from c3nav.api.schema import GeometryByLevelSchema
from c3nav.mapdata.fields import I18nField
from c3nav.mapdata.grid import grid
from c3nav.mapdata.models.access import AccessRestrictionMixin
from c3nav.mapdata.models.base import SerializableMixin, TitledMixin
from c3nav.mapdata.schemas.locations import GridSquare, DynamicLocationState
from c3nav.mapdata.schemas.model_base import BoundsSchema, LocationPoint, BoundsByLevelSchema
from c3nav.mapdata.utils.cache.local import per_request_cache
from c3nav.mapdata.utils.fields import LocationById

if TYPE_CHECKING:
    from c3nav.mapdata.render.theme import ThemeColorManager
    from c3nav.mapdata.models import Level, Space, Area, POI


class LocationSlugManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().select_related('group', 'specific')


validate_slug = RegexValidator(
    r'^[a-z0-9-]*[a-z]+[a-z0-9-]*\Z',
    # Translators: "letters" means latin letters: a-z and A-Z.
    _('Enter a valid location slug consisting of lowercase letters, numbers or hyphens, with at least one letter.'),
    'invalid'
)

possible_slug_targets = ('group', 'specific')  # todo: can we generate this?


class LocationSlug(SerializableMixin, models.Model):
    slug = models.SlugField(_('Slug'), unique=True, max_length=50, validators=[validate_slug])
    redirect = models.BooleanField(default=False)

    group = models.ForeignKey('LocationGroup', null=True, on_delete=models.CASCADE, related_name='slug_set')
    specific = models.ForeignKey('SpecificLocation', null=True, on_delete=models.CASCADE, related_name='slug_set')

    objects = LocationSlugManager()

    def get_target(self) -> Union['LocationGroup', 'SpecificLocation']:
        return self.group if self.group_id is not None else self.specific

    @property
    def target_id(self):
        return self.group_id or self.specific_id

    @cached_property
    def order(self):
        return (-1, 0)

    class Meta:
        verbose_name = _('Location Slug')
        verbose_name_plural = _('Location Slug')
        default_related_name = 'locationslugs'

        constraints = [
            models.CheckConstraint(condition=reduce(operator.or_, (
                Q(**{f'{name}__isnull': (name != set_name) for name in possible_slug_targets})
                for set_name in possible_slug_targets
            )), name="only_one_slug_target"),
            models.UniqueConstraint(fields=["group", "specific"], condition=Q(redirect=False),
                                    name="unique_non_redirect_slugs")
        ]


class Location(AccessRestrictionMixin, TitledMixin, models.Model):
    can_search = models.BooleanField(default=True, verbose_name=_('can be searched'))
    can_describe = models.BooleanField(default=True, verbose_name=_('can describe'))
    icon = models.CharField(_('icon'), max_length=32, null=True, blank=True, help_text=_('any material icons name'))
    external_url = models.URLField(_('external URL'), null=True, blank=True)

    class Meta:
        abstract = True

    @property
    def slug(self) -> str | None:
        try:
            return next(iter(locationslug.slug for locationslug in self.slug_set.all() if not locationslug.redirect))
        except StopIteration:
            return None

    @property
    def redirect_slugs(self) -> set[str]:
        return set(locationslug.slug for locationslug in self.slug_set.all() if locationslug.redirect)

    @property
    def add_search(self):
        return ' '.join((
            *self.redirect_slugs,
            *self.other_titles,
        ))

    def details_display(self, request, **kwargs):
        result = {
            'id': self.pk,
            'display': [
                (_('Type'), str(self.__class__._meta.verbose_name)),
                (_('ID'), str(self.pk)),
                (_('Slug'), self.slug),
                *(
                    (_('Title ({lang})').format(lang=get_language_info(lang)['name_translated']), title)
                    for lang, title in sorted(self.titles.items(), key=lambda item: item[0] != get_language())
                ),
                (_('Access Restriction'), self.access_restriction_id and self.access_restriction.title),
                (_('searchable'), _('Yes') if self.can_search else _('No')),
                (_('can describe'), _('Yes') if self.can_describe else _('No')),
                (_('icon'), self.effective_icon),
            ]
        }
        if self.external_url:
            result['external_url'] = {
                'title': self.external_url_label or _('Open external URL'),
                'url': self.external_url,
            }
        return result

    @property
    def effective_slug(self):
        return self.slug or str(self.pk)

    @property
    def subtitle(self):
        return ''

    @property
    def grid_square(self):
        return None

    def get_color(self, color_manager: 'ThemeColorManager') -> str | None:
        # don't filter in the query here so prefetch_related works
        result = self.get_color_sorted(color_manager)
        return None if result is None else result[1]

    def get_color_sorted(self, color_manager: 'ThemeColorManager') -> tuple[tuple, str] | None:
        # don't filter in the query here so prefetch_related works
        for group in self.groups.all():
            color = color_manager.locationgroup_fill_color(group)
            if color:  # todo: put allow_x check in here again?
                return (0, group.category.priority, group.hierarchy, group.priority), color
        return None

    @property
    def effective_icon(self):
        return self.icon or None

    @property
    def external_url_label(self):
        return None


# class SpecificLocationManager(models.Manager):
#     def get_queryset(self):
#         return super().get_queryset().select_related(
#             'level', 'space', 'area', 'poi', 'dynamiclocation'
#         )  # .prefetch_related('slug_set')  # todo: put this back in?


possible_specific_locations = ('level', 'space', 'area', 'poi', 'dynamiclocation')  # todo: can we generate this?


StaticLocationTarget: TypeAlias = Union["Level", "Space", "Area", "POI"]
DynamicLocationTarget: TypeAlias = Union["DynamicLocation"]
LocationTarget = StaticLocationTarget | DynamicLocationTarget


class SpecificLocation(Location, models.Model):
    """
    Implements :py:class:`c3nav.mapdata.schemas.locations.ListedLocationProtocol`.
    """
    locationtype = "specificlocation"
    slug_as_id = False

    groups = models.ManyToManyField('mapdata.LocationGroup', verbose_name=_('Location Groups'), blank=True)
    label_settings = models.ForeignKey('mapdata.LabelSettings', null=True, blank=True, on_delete=models.PROTECT,
                                       verbose_name=_('label settings'))
    label_override = I18nField(_('Label override'), plural_name='label_overrides', blank=True, fallback_any=True)
    import_block_data = models.BooleanField(_('don\'t change metadata on import'), default=False)
    import_block_geom = models.BooleanField(_('don\'t change geometry on import'), default=False)

    load_group_display = models.ForeignKey("LoadGroup", on_delete=models.SET_NULL, null=True, blank=True,
                                           related_name='+', verbose_name=_('display load group'))

    levels = models.ManyToManyField('Level', related_name='locations')
    spaces = models.ManyToManyField('Space', related_name='locations')
    areas = models.ManyToManyField('Area', related_name='locations')
    pois = models.ManyToManyField('POI', related_name='locations')
    dynamiclocations = models.ManyToManyField('DynamicLocation', related_name='locations')

    class Meta:
        verbose_name = _('Specific Location')
        verbose_name_plural = _('Specific Locations')
        default_related_name = 'specific_locations'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    """ Targets """

    def get_static_targets(self) -> Iterable[StaticLocationTarget]:
        """
        Get an iterator over all static location targets
        """
        # noinspection PyTypeChecker
        return chain(
            self.levels.all(),
            self.spaces.all(),
            self.areas.all(),
            self.pois.all(),
        )

    def get_dynamic_targets(self) -> Iterable[DynamicLocationTarget]:
        """
        Get an iterator over all dynamic location targets
        """
        # noinspection PyTypeChecker
        return chain(
            self.dynamiclocations.all(),
        )

    def get_targets(self) -> Iterable[LocationTarget]:
        """
        Get an iterator over all location targets
        """
        # noinspection PyTypeChecker
        return chain(
            self.get_static_targets(),
            self.get_dynamic_targets(),
        )

    """ Main Properties """

    @cached_property
    def dynamic(self) -> int:
        return len(self.dynamiclocations.all())

    @property
    def effective_icon(self):
        icon = super().effective_icon
        if icon:
            return icon
        return next(iter(chain(
            (group.icon for group in self.groups.all() if group.icon),
            (None, )
        )))

    @property
    def effective_label_settings(self):
        if self.label_settings:
            return self.label_settings
        for group in self.groups.all():
            if group.label_settings:
                return group.label_settings
        return None

    @cached_property
    def order(self):
        groups = tuple(self.groups.all())
        if not groups:
            return (0, 0, 0)
        return (0, groups[0].category.priority, groups[0].priority)

    @cached_property
    def describing_groups(self):
        groups = tuple(self.groups.all() if 'groups' in getattr(self, '_prefetched_objects_cache', ()) else ())
        groups = tuple(group for group in groups if group.can_describe)
        return groups

    @property
    def external_url_label(self):
        for group in self.groups.all():
            if group.external_url_label:
                return group.external_url_label
        return None

    @property
    def groups_by_category(self):
        groups_by_category = {}
        for group in self.groups.all():
            groups_by_category.setdefault(group.category, []).append(group.pk)
        groups_by_category = {category.name: (items[0] if items else None) if category.single else items
                              for category, items in groups_by_category.items()}
        return groups_by_category

    """ Points / Bounds / Grid """

    @property
    def points(self) -> list[LocationPoint]:
        return list(filter(None, (target.point for target in self.get_static_targets())))

    @property
    def dynamic_points(self) -> list[LocationPoint]:
        return list(filter(None, (target.point for target in self.get_dynamic_targets())))

    @staticmethod
    def get_bounds(*, targets: Iterable[LocationTarget]):
        from c3nav.mapdata.utils.locations import merge_bounds
        return merge_bounds(*filter(None, (target.bounds for target in targets)))

    @cached_property
    def bounds(self) -> BoundsByLevelSchema:
        return self.get_bounds(targets=self.get_static_targets())

    @cached_property
    def dynamic_bounds(self) -> BoundsByLevelSchema:
        return self.get_bounds(targets=self.get_targets())

    @staticmethod
    def get_grid_square(*, bounds) -> GridSquare:
        # todo: move this outside of class?
        # todo: maybe only merge bounds if it's all in one level… but for multi-level rooms its nice! find solution?
        if not bounds:
            return ""
        zipped = tuple(zip(*(chain(*level_bounds) for level_bounds in bounds.values())))
        return grid.get_squares_for_bounds((min(zipped[0]), min(zipped[1]), max(zipped[2]), max(zipped[3])))

    @property
    def grid_square(self) -> GridSquare:
        return self.get_grid_square(bounds=self.bounds)

    @property
    def dynamic_grid_square(self) -> GridSquare:
        return self.get_grid_square(bounds=self.dynamic_bounds)

    """ Subtitle """

    def get_target_subtitle(self, *, dynamic: bool) -> Optional[str]:
        static_targets = tuple(self.get_static_targets())
        dynamic_targets = tuple(self.get_dynamic_targets())
        if len(static_targets) + len(dynamic_targets) == 1:
            if static_targets:
                return static_targets[0].subtitle
            elif dynamic:
                return dynamic_targets[0].subtitle  # todo: make this work right
        # todo: make this work right for multiple targets
        return None

    def get_subtitle(self, *, target_subtitle: Optional[str], grid_square: GridSquare) -> str:
        # get subtitle from highest ranked describing group
        subtitle = self.describing_groups[0].title if self.describing_groups else None

        # add grid square if available
        if grid_square:
            subtitle = (
                format_lazy(_('{describing_group}, {grid_square}'),
                            describing_group=subtitle,
                            grid_square=self.grid_square)
                if subtitle else self.grid_square
            )

        # add subtitle from target(s)
        if target_subtitle:
            subtitle = (
                format_lazy(_('{subtitle}, {space_level_etc}'), subtitle=subtitle, space_level_etc=target_subtitle)
                if subtitle else target_subtitle
            )

        # fallback if there is no subtitle  # todo: this could probably be better?
        if subtitle is not None:
            return subtitle
        return _('Location') if len(tuple(self.get_targets())) == 1 else _('Locations')

    @property
    def subtitle(self):
        return self.get_subtitle(
            target_subtitle=self.get_target_subtitle(dynamic=False),
            grid_square=self.grid_square,
        )

    @property
    def dynamic_subtitle(self):
        return self.get_subtitle(
            target_subtitle=self.get_target_subtitle(dynamic=False),
            grid_square=self.dynamic_grid_square,
        )

    """ Other Stuff """

    @property
    def dynamic_state(self) -> Optional[DynamicLocationState]:
        if not self.dynamic:
            return None
        return DynamicLocationState(
            subtitle=self.dynamic_subtitle,
            grid_square=self.dynamic_grid_square,
            dynamic_points=self.dynamic_points,
            bounds=self.dynamic_bounds,
            nearby=None,  # todo: add nearby information
        )

    def get_geometry(self, request) -> GeometryByLevelSchema:
        # todo: eventually include dynamic targets in here?
        result = {}
        for target in self.get_static_targets():
            for level_id, geometries in target.get_geometry(request).items():
                result.setdefault(level_id, []).extend(geometries)
        return result

    def get_geometry_or_points(self, request) -> GeometryByLevelSchema:
        # todo: eventually include dynamic targets in here?
        result = {}
        for target in self.get_static_targets():
            target_geometry = target.get_geometry(request)
            if target_geometry:
                for level_id, geometries in target_geometry.items():
                    result.setdefault(level_id, []).extend(geometries)
            else:
                for level_id, x, y in target.points:
                    result.setdefault(level_id, []).append(Point(x, y))
        return result

    def details_display(self, request, editor_url=True, **kwargs):
        result = super().details_display(request, **kwargs)

        groupcategories = {}
        for group in self.groups.all():
            groupcategories.setdefault(group.category, []).append(group)

        if grid.enabled:
            grid_square = self.grid_square
            if grid_square is not None:
                grid_square_title = (_('Grid Squares') if grid_square and '-' in grid_square else _('Grid Square'))
                result['display'].insert(3, (grid_square_title, grid_square or None))

        for category, groups in sorted(groupcategories.items(), key=lambda item: item[0].priority):
            result['display'].insert(3, (
                category.title if category.single else category.title_plural,
                tuple({
                    'id': group.pk,
                    'slug': group.effective_slug,
                    'title': group.title,
                    'can_search': group.can_search,
                } for group in sorted(groups, key=attrgetter('priority'), reverse=True))
            ))

        if editor_url:
            result['editor_url'] = reverse('editor.specific_locations.edit', kwargs={'pk': self.pk})

        return result

    """ Changed Geometries """

    def register_changed_geometries(self, force=False):
        changed = (
          self.level_id, self.space_id, self.area_id, self.poi_id, self.dynamiclocation_id
        ) != self._orig["target"]
        if changed and any(self._orig["target"]):
            if any(self._orig["target"]):
                from c3nav.mapdata.models import Level, Space, Area, POI
                target_i = next(iter(i for i, t in enumerate(self._orig["target"]) if t))
                target_model = (Level, Space, Area, POI, DynamicLocation)[target_i]
                target_id = self._orig["target"][target_i]
                for old_target in target_model.objects.filter(pk=target_id):
                    old_target.register_change(force=True)
        if changed or force:
            for target in self.get_targets():
                target.register_change(force=True)

    def pre_save_changed_geometries(self):
        self.register_changed_geometries()

    def save(self, *args, **kwargs):
        self.pre_save_changed_geometries()
        super().save(*args, **kwargs)

    def pre_delete_changed_geometries(self):
        self.register_changed_geometries(force=True)

    def delete(self, *args, **kwargs):
        self.pre_delete_changed_geometries()
        super().delete(*args, **kwargs)


class SpecificLocationTargetMixin(models.Model):
    class Meta:
        abstract = True

    @cached_property
    def sorted_locations(self) -> list[SpecificLocation]:
        """
        highest priority first
        """
        # noinspection PyUnresolvedReferences
        return sorted(self.locations.all(), key=attrgetter("order"), reverse=True)

    @property
    def effective_icon(self) -> str | None:
        # todo: do we want this method, at all?
        # todo: enhance performance using generator
        icons = [location.effective_icon for location in self.sorted_locations if location.effective_icon]
        if not icons:
            return None
        return icons[0]

    @property
    def title(self) -> str:
        return self.sorted_locations[0].title if self.sorted_locations else None

    def get_color(self, color_manager: 'ThemeColorManager') -> str | None:
        # todo: enhance performance using generator
        colors = list(filter(None, [location.get_color(color_manager) for location in self.sorted_locations]))
        if not colors:
            return None
        return colors[0]

    def get_geometry(self, request) -> GeometryByLevelSchema:
        return {}

    @property
    def point(self) -> Optional[LocationPoint]:
        return None

    @property
    def points(self) -> list[LocationPoint]:
        return []

    @property
    def bounds(self) -> Optional[BoundsSchema]:
        return None

    @property
    def grid_square(self):
        return None

    @property
    def subtitle(self):
        return None

    def get_color_sorted(self, color_manager) -> tuple[tuple, str] | None:
        # todo: enhance performance using generator
        color_sorted = list(filter(None, [location.get_color_sorted(color_manager)
                                          for location in self.sorted_locations]))
        if not color_sorted:
            return None
        return color_sorted[0]

    def get_location(self, can_describe=False) -> Optional[SpecificLocation]:
        # todo: do we want to get rid of this?
        return next(iter((*(location for location in self.sorted_locations if location.can_describe), None)))


class LocationGroupCategory(SerializableMixin, models.Model):
    name = models.SlugField(_('Name'), unique=True, max_length=50)
    single = models.BooleanField(_('single selection'), default=False)
    title = I18nField(_('Title'), plural_name='titles', fallback_any=True)
    title_plural = I18nField(_('Title (Plural)'), plural_name='titles_plural', fallback_any=True)
    help_text = I18nField(_('Help text'), plural_name='help_texts', fallback_any=True, fallback_value='')
    allow_levels = models.BooleanField(_('allow levels'), db_index=True, default=True)
    allow_spaces = models.BooleanField(_('allow spaces'), db_index=True, default=True)
    allow_areas = models.BooleanField(_('allow areas'), db_index=True, default=True)
    allow_pois = models.BooleanField(_('allow pois'), db_index=True, default=True)
    allow_dynamic_locations = models.BooleanField(_('allow dynamic locations'), db_index=True, default=True)
    priority = models.IntegerField(default=0, db_index=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._orig = {"priority": self.priority}

    class Meta:
        verbose_name = _('Location Group Category')
        verbose_name_plural = _('Location Group Categories')
        default_related_name = 'locationgroupcategories'
        ordering = ('-priority', )

    def register_changed_geometries(self):
        for group in  self.groups.prefetch_related('groups__specific_locations'):
            group.register_changed_geometries()

    def pre_save_changed_geometries(self):
        if not self._state.adding and any(getattr(self, attname) != value for attname, value in self._orig.items()):
            self.register_changed_geometries()

    def save(self, *args, **kwargs):
        self.pre_save_changed_geometries()
        super().save(*args, **kwargs)

    def pre_delete_changed_geometries(self):
        self.register_changed_geometries()

    def delete(self, *args, **kwargs):
        self.pre_delete_changed_geometries()
        super().delete(*args, **kwargs)


class LocationGroupManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().select_related('category')  # .prefetch_related('slug_set')  # todo: put this back in?


class LocationGroup(Location, models.Model):
    """
    Implements :py:class:`c3nav.mapdata.schemas.locations.ListedLocationProtocol`.
    """
    locationtype = "locationgroup"
    slug_as_id = False

    class CanReportMissing(models.TextChoices):
        DONT_OFFER = "dont_offer", _("don't offer")
        REJECT = "reject", _("offer in first step, then reject")
        SINGLE = "single", _("offer in first step, exclusive choice")
        MULTIPLE = "multiple", _("offer if nothing in the first step matches, multiple choice")

    class CanReportMistake(models.TextChoices):
        ALLOW = "allow", _("allow")
        REJECT = "reject", _("reject for all locations with this group")

    category = models.ForeignKey(LocationGroupCategory, related_name='groups', on_delete=models.PROTECT,
                                 verbose_name=_('Category'))
    priority = models.IntegerField(default=0, db_index=True)
    hierarchy = models.IntegerField(default=0, db_index=True, verbose_name=_('hierarchy'))
    label_settings = models.ForeignKey('mapdata.LabelSettings', null=True, blank=True, on_delete=models.PROTECT,
                                       verbose_name=_('label settings'),
                                       help_text=_('unless location specifies otherwise'))
    can_report_missing = models.CharField(_('report missing location'), choices=CanReportMissing.choices,
                                          default=CanReportMissing.DONT_OFFER, max_length=16)
    can_report_mistake = models.CharField(_('report mistakes'), choices=CanReportMistake.choices,
                                          default=CanReportMistake.ALLOW, max_length=16)

    description = I18nField(_('description'), plural_name='descriptions', blank=True, fallback_any=True,
                            fallback_value="", help_text=_('to aid with selection in the report form'))
    report_help_text = I18nField(_('report help text'), plural_name='report_help_texts', blank=True, fallback_any=True,
                                 fallback_value="", help_text=_('to explain the report form or rejection'))

    color = models.CharField(null=True, blank=True, max_length=32, verbose_name=_('background color'))
    in_legend = models.BooleanField(default=False, verbose_name=_('show in legend (if color set)'))
    hub_import_type = models.CharField(max_length=100, verbose_name=_('hub import type'), null=True, blank=True,
                                       unique=True,
                                       help_text=_('assign this group to imported hub locations of this type'))
    external_url_label = I18nField(_('external URL label'), plural_name='external_url_labels', blank=True,
                                   fallback_any=True, fallback_value="")

    load_group_contribute = models.ForeignKey("LoadGroup", on_delete=models.SET_NULL, null=True, blank=True,
                                              verbose_name=_('contribute to load group'))

    objects = LocationGroupManager()

    class Meta:
        verbose_name = _('Location Group')
        verbose_name_plural = _('Location Groups')
        default_related_name = 'locationgroups'
        ordering = ('-category__priority', '-priority')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        deferred_fields = self.get_deferred_fields()
        self._orig = {
            key: getattr(self, key)
            for key in ("priority", "hierarchy", "category_id", "color")
            if key not in deferred_fields
        }

    locations = []

    def details_display(self, request, *, editor_url=True, **kwargs):
        result = super().details_display(request, **kwargs)
        result['display'].insert(3, (_('Category'), self.category.title))
        result['display'].extend([
            (_('color'), self.color),
            (_('priority'), str(self.priority)),
        ])
        if editor_url:
            result['editor_url'] = reverse('editor.locationgroups.edit', kwargs={'pk': self.pk})
        return result

    @property
    def title_for_forms(self):
        attributes = []
        if self.can_search:
            attributes.append(_('search'))
        if self.can_describe:
            attributes.append(_('describe'))
        if self.color:
            attributes.append(_('color'))
        if not attributes:
            attributes.append(_('internal'))
        return self.title + ' ('+', '.join(str(s) for s in attributes)+')'

    def register_changed_geometries(self):
        for obj in self.specific_locations.all():
            obj.register_change(force=True)

    @property
    def subtitle(self):
        result = self.category.title
        if hasattr(self, 'locations'):  # todo: improve?
            return format_lazy(_('{category_title}, {num_locations}'),
                               category_title=result,
                               num_locations=(ngettext_lazy('%(num)d location', '%(num)d locations', 'num') %
                                              {'num': len(self.locations)}))
        return result

    @cached_property
    def order(self):
        return (1, self.category.priority, self.priority)

    def pre_save_changed_geometries(self):
        if not self._state.adding and any(getattr(self, attname) != value for attname, value in self._orig.items()):
            self.register_changed_geometries()

    def save(self, *args, **kwargs):
        self.pre_save_changed_geometries()
        super().save(*args, **kwargs)

    def pre_delete_changed_geometries(self):
        self.register_changed_geometries()

    def delete(self, *args, **kwargs):
        self.pre_delete_changed_geometries()
        super().delete(*args, **kwargs)


class LabelSettings(SerializableMixin, models.Model):
    title = I18nField(_('Title'), plural_name='titles', fallback_any=True)
    min_zoom = models.DecimalField(_('min zoom'), max_digits=3, decimal_places=1, default=-10,
                                   validators=[MinValueValidator(Decimal('-10')),
                                               MaxValueValidator(Decimal('10'))])
    max_zoom = models.DecimalField(_('max zoom'), max_digits=3, decimal_places=1, default=10,
                                   validators=[MinValueValidator(Decimal('-10')),
                                               MaxValueValidator(Decimal('10'))])
    font_size = models.IntegerField(_('font size'), default=12,
                                    validators=[MinValueValidator(12),
                                                MaxValueValidator(30)])

    class Meta:
        verbose_name = _('Label Settings')
        verbose_name_plural = _('Label Settings')
        default_related_name = 'labelsettings'
        ordering = ('min_zoom', '-font_size')


class LoadGroup(SerializableMixin, models.Model):
    name = models.CharField(_('Name'), unique=True, max_length=50)  # a slugfield would forbid periods

    @property
    def title(self):
        return self.name

    class Meta:
        verbose_name = _('Load group')
        verbose_name_plural = _('Load groups')
        default_related_name = 'labelgroup'


class CustomLocationProxyMixin:
    request = None

    def get_custom_location(self, request=None):
        raise NotImplementedError


class DynamicLocation(SpecificLocationTargetMixin, AccessRestrictionMixin, models.Model):
    position_secret = models.CharField(_('position secret'), max_length=32, null=True, blank=True)

    class Meta:
        verbose_name = _('Dynamic location')
        verbose_name_plural = _('Dynamic locations')
        default_related_name = 'dynamiclocations'

    def register_change(self, force=False):
        pass

    def get_custom_location(self, request=None):
        if not self.position_secret:
            return None
        try:
            return Position.objects.get(secret=self.position_secret).get_custom_location(
                request=request if request is not None else self.request
            )
        except Position.DoesNotExist:
            return None


def get_position_secret():
    return get_random_string(32, string.ascii_letters+string.digits)


class Position(models.Model):
    """
    Implements :py:class:`c3nav.mapdata.schemas.locations.LocationProtocol`.
    """
    objects = None
    locationtype = "position"
    slug_as_id = True  # todo: implement this!!

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(_('name'), max_length=32)
    short_name = models.CharField(_('abbreviation'), help_text=_('two characters maximum'), max_length=2)
    secret = models.CharField(_('secret'), unique=True, max_length=32, default=get_position_secret)
    last_coordinates_update = models.DateTimeField(_('last coordinates update'), null=True)
    timeout = models.PositiveSmallIntegerField(_('timeout (in seconds)'), default=0, blank=True,
                                               help_text=_('0 for no timeout'))
    coordinates_id = models.CharField(_('coordinates'), null=True, blank=True, max_length=48)

    coordinates = LocationById()

    dynamic = 1
    subtitle = _('Position')
    effective_icon = "my_location"
    grid_square = None

    can_search = True
    can_describe = False

    class Meta:
        verbose_name = _('Dynamic position')
        verbose_name_plural = _('Dynamic position')
        default_related_name = 'dynamic_positions'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.timeout and self.last_coordinates_update:
            end_time = self.last_coordinates_update + timedelta(seconds=self.timeout)
            if timezone.now() >= end_time:
                self.coordinates = None
                self.last_coordinates_update = end_time

    def get_custom_location(self, request=None):
        # todo: GET RID OF THIS
        if request is not None:
            self.request = request  # todo: this is ugly, yes
        return self.coordinates

    @property
    def slug(self):
        return 'm:%s' % self.secret

    @property
    def effective_slug(self):
        return self.slug

    @property
    def title(self):
        return self.name

    @property
    def dynamic_subtitle(self):
        # todo: implement request permissions/visibility for description
        custom_location = self.coordinates
        if not custom_location:
            return _('currently unavailable')
        return '%s, %s, %s' % (
            _('Position'),
            custom_location.title,
            custom_location.subtitle,
        )

    @property
    def dynamic_grid_square(self):
        custom_location = self.coordinates
        if not custom_location:
            return None
        return custom_location.grid_square

    @property
    def dynamic_bounds(self):
        custom_location = self.coordinates
        if not custom_location:
            return None
        return custom_location.grid_square

    @property
    def dynamic_state(self) -> DynamicLocationState:
        custom_location = self.coordinates
        if not custom_location:
            return DynamicLocationState(
                subtitle=_('currently unavailable'),
                grid_square=None,
                dynamic_points=[],
                bounds={},
                nearby=None,
            )
        return DynamicLocationState(
            subtitle='%s, %s, %s' % (
                _('Position'),
                custom_location.title,
                custom_location.subtitle,
            ),
            grid_square=custom_location.grid_square,
            dynamic_points=custom_location.points,
            bounds=custom_location.bounds,
            nearby=None,  # todo: add nearby information
        )

    @property
    def points(self):
        return []

    @classmethod
    def user_has_positions(cls, user):
        if not user.is_authenticated:
            return False
        cache_key = 'user_has_positions:%d' % user.pk
        result = per_request_cache.get(cache_key, None)
        if result is None:
            result = cls.objects.filter(owner=user).exists()
            per_request_cache.set(cache_key, result, 600)
        return result

    # todo: expose short_name again somehow

    def details_display(self, **kwargs):
        return {
            'id': self.pk,
            'display': [
                (_('Type'), self.__class__._meta.verbose_name),
                (_('ID'), str(self.pk)),
                (_('Title'), self.name),
                (_('Slug'), self.slug),
                (_('searchable'), _('No')),
                (_('can describe'), _('No')),
                (_('icon'), None),
            ],
        }

    def get_geometry(self, request) -> GeometryByLevelSchema:
        return {}

    def get_geometry_or_points(self, request) -> GeometryByLevelSchema:
        return {}

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            transaction.on_commit(lambda: cache.delete('user_has_positions:%d' % self.owner_id))

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            super().delete(*args, **kwargs)
            transaction.on_commit(lambda: cache.delete('user_has_positions:%d' % self.owner_id))
