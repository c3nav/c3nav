import operator
import string
import typing
from datetime import timedelta
from decimal import Decimal
from functools import reduce
from itertools import chain
from operator import attrgetter

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
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from c3nav.mapdata.fields import I18nField
from c3nav.mapdata.grid import grid
from c3nav.mapdata.models.access import AccessRestrictionMixin
from c3nav.mapdata.models.base import SerializableMixin, TitledMixin
from c3nav.mapdata.schemas.model_base import BoundsSchema, LocationPoint
from c3nav.mapdata.utils.cache.local import per_request_cache
from c3nav.mapdata.utils.fields import LocationById

if typing.TYPE_CHECKING:
    from c3nav.mapdata.render.theme import ThemeColorManager


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
    LOCATION_TYPE_CODES = {
        'SpecificLocation': 'l',
        'LocationGroup': 'g'
    }
    LOCATION_TYPE_BY_CODE = {
        **{code: model_name for model_name, code in LOCATION_TYPE_CODES.items()}
    }

    slug = models.SlugField(_('Slug'), unique=True, max_length=50, validators=[validate_slug])
    redirect = models.BooleanField(default=False)

    group = models.ForeignKey('LocationGroup', null=True, on_delete=models.CASCADE, related_name='slug_set')
    specific = models.ForeignKey('SpecificLocation', null=True, on_delete=models.CASCADE, related_name='slug_set')

    objects = LocationSlugManager()

    def get_target(self) -> typing.Union['LocationGroup', 'SpecificLocation']:
        return self.group if self.group_id is not None else self.specific

    def details_display(self, **kwargs):
        result = super().details_display(**kwargs)
        result['display'].insert(2, (_('Slug'), self.effective_slug))
        return result

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

    def details_display(self, **kwargs):
        result = super().details_display(**kwargs)
        result['display'].extend([
            (_('searchable'), _('Yes') if self.can_search else _('No')),
            (_('can describe'), _('Yes') if self.can_describe else _('No')),
            (_('icon'), self.effective_icon),
        ])

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


class SpecificLocation(Location, models.Model):
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

    def get_targets(self):
        return chain(
            self.levels.all(),
            self.spaces.all(),
            self.areas.all(),
            self.pois.all(),
            self.dynamiclocations.all(),
        )

    @property
    def effective_label_settings(self):
        if self.label_settings:
            return self.label_settings
        for group in self.groups.all():
            if group.label_settings:
                return group.label_settings
        return None

    @property
    def points(self) -> list[LocationPoint]:
        return list(filter(None, (target.point for target in self.get_targets())))

    @property
    def bounds(self) -> BoundsSchema:
        # todo: per level?
        zipped_bounds = tuple(zip(*(chain(*target.bounds) for target in self.get_targets())))
        return (min(zipped_bounds[0]), min(zipped_bounds[1])), (max(zipped_bounds[2]), max(zipped_bounds[3]))

    @property
    def grid_square(self):
        # todo: per level? remove if multi-level?
        return grid.get_squares_for_bounds(chain(*self.bounds))

    @property
    def groups_by_category(self):
        groups_by_category = {}
        for group in self.groups.all():
            groups_by_category.setdefault(group.category, []).append(group.pk)
        groups_by_category = {category.name: (items[0] if items else None) if category.single else items
                              for category, items in groups_by_category.items()}
        return groups_by_category

    def details_display(self, **kwargs):
        result = super().details_display(**kwargs)

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

        return result

    @cached_property
    def describing_groups(self):
        groups = tuple(self.groups.all() if 'groups' in getattr(self, '_prefetched_objects_cache', ()) else ())
        groups = tuple(group for group in groups if group.can_describe)
        return groups

    @property
    def subtitle(self):
        subtitle = self.describing_groups[0].title if self.describing_groups else None
        if self.grid_square:
            if subtitle:
                subtitle = format_lazy(_('{describing_group}, {grid_square}'),
                                       describing_group=subtitle,
                                       grid_square=self.grid_square)
            else:
                subtitle = self.grid_square
        targets = tuple(self.get_targets())
        if len(targets) == 1:
            target_subtitle = targets[0].subtitle
        else:
            # todo: merge these, maybe?
            target_subtitle = None
        if target_subtitle:
            if subtitle:
                subtitle = format_lazy(_('{subtitle}, {space_level_etc}'),
                                       subtitle=subtitle,
                                       space_level_etc=target_subtitle)
            else:
                subtitle = target_subtitle
        if subtitle is None:
            # todo: this could probably be better?
            subtitle = _('Location') if len(targets) == 1 else _('Locations')
        return subtitle

    @cached_property
    def order(self):
        groups = tuple(self.groups.all())
        if not groups:
            return (0, 0, 0)
        return (0, groups[0].category.priority, groups[0].priority)

    @property
    def effective_icon(self):
        icon = super().effective_icon
        if icon:
            return icon
        return next(iter((icon for icon in chain(
            (group.icon for group in self.groups.all()),
            ("location", )
        ) if icon)))

    @property
    def external_url_label(self):
        for group in self.groups.all():
            if group.external_url_label:
                return group.external_url_label
        return None

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

    @property
    def point(self) -> typing.Optional[LocationPoint]:
        return None

    @property
    def bounds(self) -> typing.Optional[BoundsSchema]:
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

    def get_location(self, can_describe=False) -> typing.Optional[SpecificLocation]:
        # todo: do we want to get rid of this?
        return self.sorted_locations[0] if self.sorted_locations else None


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

    def details_display(self, editor_url=True, **kwargs):
        result = super().details_display(**kwargs)
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

    @property
    def available(self):
        return self.get_custom_location() is not None

    @property
    def x(self):
        return self.get_custom_location().x

    @property
    def y(self):
        return self.get_custom_location().y

    @property
    def level(self):
        return self.get_custom_location().level

    def serialize_position(self, request=None):
        raise NotImplementedError


class DynamicLocation(CustomLocationProxyMixin, SpecificLocationTargetMixin, AccessRestrictionMixin, models.Model):
    position_secret = models.CharField(_('position secret'), max_length=32, null=True, blank=True)

    class Meta:
        verbose_name = _('Dynamic location')
        verbose_name_plural = _('Dynamic locations')
        default_related_name = 'dynamiclocations'

    def register_change(self, force=False):
        pass

    def serialize_position(self, request=None):
        # todo: make this pretty
        custom_location = self.get_custom_location(request=request)
        if custom_location is None:
            return {
                'available': False,
                'id': self.pk,
                'slug': self.slug,
                'icon': self.effective_icon,
                'title': str(self.title),
                'subtitle': '%s %s, %s' % (_('currently unavailable'), _('(moving)'), self.subtitle)
            }
        from c3nav.mapdata.schemas.models import CustomLocationSchema
        result = CustomLocationSchema.model_validate(custom_location).model_dump()
        result.update({
            'available': True,
            'id': self.pk,
            'slug': self.slug,
            'icon': self.effective_icon,
            'title': str(self.title),
            'subtitle': '%s %s%s, %s' % (
                _('(moving)'),
                ('%s, ' % self.subtitle) if self.describing_groups else '',
                result['title'],
                result['subtitle']
            ),
        })
        return result

    def get_custom_location(self, request=None):
        if not self.position_secret:
            return None
        try:
            return Position.objects.get(secret=self.position_secret).get_custom_location(
                request=request if request is not None else self.request
            )
        except Position.DoesNotExist:
            return None

    def details_display(self, editor_url=True, **kwargs):
        result = super().details_display(**kwargs)
        if editor_url:
            result['editor_url'] = reverse('editor.dynamic_locations.edit', kwargs={'pk': self.pk})
        return result


def get_position_secret():
    return get_random_string(32, string.ascii_letters+string.digits)


class Position(CustomLocationProxyMixin, models.Model):
    locationtype = "position"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(_('name'), max_length=32)
    short_name = models.CharField(_('abbreviation'), help_text=_('two characters maximum'), max_length=2)
    secret = models.CharField(_('secret'), unique=True, max_length=32, default=get_position_secret)
    last_coordinates_update = models.DateTimeField(_('last coordinates update'), null=True)
    timeout = models.PositiveSmallIntegerField(_('timeout (in seconds)'), default=0, blank=True,
                                               help_text=_('0 for no timeout'))
    coordinates_id = models.CharField(_('coordinates'), null=True, blank=True, max_length=48)

    can_search = True
    can_describe = False

    coordinates = LocationById()

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
        if request is not None:
            self.request = request  # todo: this is ugly, yes
        return self.coordinates

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

    def serialize_position(self, request=None):
        # todo: make this pretty
        custom_location = self.get_custom_location(request=request)
        if custom_location is None:
            return {
                'id': 'm:%s' % self.secret,
                'slug': 'm:%s' % self.secret,
                'effective_slug': 'm:%s' % self.secret,
                'available': False,
                'icon': 'my_location',
                'effective_icon': 'my_location',
                'title': self.name,
                'short_name': self.short_name,
                'subtitle': _('currently unavailable'),
            }
        # todo: is this good?
        from c3nav.mapdata.schemas.models import CustomLocationLocationSchema
        result = CustomLocationLocationSchema.model_validate(custom_location).model_dump()
        result.update({
            'available': True,
            'id': 'm:%s' % self.secret,
            'slug': 'm:%s' % self.secret,
            'effective_slug': 'm:%s' % self.secret,
            'icon': 'my_location',
            'title': self.name,
            'short_name': self.short_name,
            'subtitle': '%s, %s, %s' % (
                _('Position'),
                result['title'],
                result['subtitle']
            ),
        })
        return result

    @property
    def title(self):
        return self.name

    @property
    def slug(self):
        return 'm:%s' % self.secret

    @property
    def subtitle(self):
        return _('Position')

    @property
    def icon(self):
        return 'my_location'

    @property
    def effective_icon(self):
        return self.icon

    @property
    def effective_slug(self):
        return self.slug

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

    def get_geometry(self, *args, **kwargs):
        return None

    level_id = None

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            transaction.on_commit(lambda: cache.delete('user_has_positions:%d' % self.owner_id))

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            super().delete(*args, **kwargs)
            transaction.on_commit(lambda: cache.delete('user_has_positions:%d' % self.owner_id))
