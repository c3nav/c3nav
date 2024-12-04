import string
import typing
from contextlib import suppress
from datetime import timedelta
from decimal import Decimal
from operator import attrgetter

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import FieldDoesNotExist
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models import Prefetch
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
from c3nav.mapdata.utils.fields import LocationById
from c3nav.mapdata.utils.models import get_submodels

if typing.TYPE_CHECKING:
    from c3nav.mapdata.render.theme import ThemeColorManager


class LocationSlugManager(models.Manager):
    def get_queryset(self):
        result = super().get_queryset()
        if self.model == LocationSlug:
            for model in get_submodels(Location) + [LocationRedirect]:
                result = result.select_related(model._meta.default_related_name)
                try:
                    model._meta.get_field('space')
                except FieldDoesNotExist:
                    pass
                else:
                    result = result.select_related(model._meta.default_related_name+'__space')
        return result

    def select_related_target(self):
        if self.model != LocationSlug:
            raise TypeError
        qs = self.get_queryset()
        qs = qs.select_related('locationredirects__target',
                               *('locationredirects__target__'+model._meta.default_related_name
                                 for model in get_submodels(Location) + [LocationRedirect]))
        return qs


validate_slug = RegexValidator(
    r'^[a-z0-9]+(--?[a-z0-9]+)*\Z',
    # Translators: "letters" means latin letters: a-z and A-Z.
    _('Enter a valid location slug consisting of lowercase letters, numbers or hyphens, '
      'not starting or ending with hyphens or containing consecutive hyphens.'),
    'invalid'
)


class LocationSlug(SerializableMixin, models.Model):
    LOCATION_TYPE_CODES = {
        'Level': 'l',
        'Space': 's',
        'Area': 'a',
        'POI': 'p',
        'LocationGroup': 'g'
    }
    LOCATION_TYPE_BY_CODE = {code: model_name for model_name, code in LOCATION_TYPE_CODES.items()}
    slug = models.SlugField(_('Slug'), unique=True, null=True, blank=True, max_length=50, validators=[validate_slug])

    objects = LocationSlugManager()

    def get_child(self):
        for model in get_submodels(Location)+[LocationRedirect]:
            with suppress(AttributeError):
                return getattr(self, model._meta.default_related_name)
        return None

    @property
    def effective_slug(self):
        return self.slug

    def details_display(self, **kwargs):
        result = super().details_display(**kwargs)
        result['display'].insert(2, (_('Slug'), self.effective_slug))
        return result

    @cached_property
    def order(self):
        return (-1, 0)

    class Meta:
        verbose_name = _('Location with Slug')
        verbose_name_plural = _('Location with Slug')
        default_related_name = 'locationslugs'


class Location(LocationSlug, AccessRestrictionMixin, TitledMixin, models.Model):
    can_search = models.BooleanField(default=True, verbose_name=_('can be searched'))
    can_describe = models.BooleanField(default=True, verbose_name=_('can describe'))
    icon = models.CharField(_('icon'), max_length=32, null=True, blank=True, help_text=_('any material icons name'))

    class Meta:
        abstract = True

    @property
    def add_search(self):
        return ' '.join((
            *(redirect.slug for redirect in self.redirects.all()),
            *self.other_titles,
        ))

    def details_display(self, **kwargs):
        result = super().details_display(**kwargs)
        result['display'].extend([
            (_('searchable'), _('Yes') if self.can_search else _('No')),
            (_('can describe'), _('Yes') if self.can_describe else _('No')),
            (_('icon'), self.effective_icon),
        ])
        return result

    @property
    def effective_slug(self):
        if self.slug is None:
            code = self.LOCATION_TYPE_CODES.get(self.__class__.__name__)
            if code is not None:
                return code+':'+str(self.id)
        return self.slug

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
            if color and getattr(group.category, 'allow_'+self.__class__._meta.default_related_name):
                return (0, group.category.priority, group.hierarchy, group.priority), color
        return None

    @property
    def effective_icon(self):
        return self.icon or None


class SpecificLocation(Location, models.Model):
    groups = models.ManyToManyField('mapdata.LocationGroup', verbose_name=_('Location Groups'), blank=True)
    label_settings = models.ForeignKey('mapdata.LabelSettings', null=True, blank=True, on_delete=models.PROTECT,
                                       verbose_name=_('label settings'))
    label_override = I18nField(_('Label override'), plural_name='label_overrides', blank=True, fallback_any=True)
    external_url = models.URLField(_('external URL'), null=True, blank=True)
    import_block_data = models.BooleanField(_('don\'t change metadata on import'), default=False)
    import_block_geom = models.BooleanField(_('don\'t change geometry on import'), default=False)

    class Meta:
        abstract = True

    @property
    def effective_label_settings(self):
        if self.label_settings:
            return self.label_settings
        for group in self.groups.all():
            if group.label_settings:
                return group.label_settings
        return None

    @property
    def groups_by_category(self):
        groups_by_category = {}
        for group in self.groups.all():
            groups_by_category.setdefault(group.category, []).append(group.pk)
        groups_by_category = {category.name: (items[0] if items else None) if category.single else items
                  for category, items in groups_by_category.items()
                  if getattr(category, 'allow_' + self.__class__._meta.default_related_name)}
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

        if self.external_url:
            result['display'].insert(3, (_('External URL'), {
                'title': _('Open'),
                'url': self.external_url,
            }))

        return result

    @cached_property
    def describing_groups(self):
        groups = tuple(self.groups.all() if 'groups' in getattr(self, '_prefetched_objects_cache', ()) else ())
        groups = tuple(group for group in groups if group.can_describe)
        return groups

    @property
    def subtitle(self):
        subtitle = self.describing_groups[0].title if self.describing_groups else self.__class__._meta.verbose_name
        if self.grid_square:
            return '%s, %s' % (subtitle, self.grid_square)
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
        for group in self.groups.all():
            if group.icon and getattr(group.category, 'allow_' + self.__class__._meta.default_related_name):
                return group.icon
        return None


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
        self.orig_priority = self.priority

    class Meta:
        verbose_name = _('Location Group Category')
        verbose_name_plural = _('Location Group Categories')
        default_related_name = 'locationgroupcategories'
        ordering = ('-priority', )

    def register_changed_geometries(self):
        from c3nav.mapdata.models.geometry.space import SpaceGeometryMixin
        query = self.groups.all()
        for model in get_submodels(SpecificLocation):
            related_name = model._meta.default_related_name
            subquery = model.objects.all()
            if issubclass(model, SpaceGeometryMixin):
                subquery = subquery.select_related('space')
            query.prefetch_related(Prefetch('groups__'+related_name, subquery))

        for group in query:
            group.register_changed_geometries(do_query=False)

    def save(self, *args, **kwargs):
        if self.pk and self.priority != self.orig_priority:
            self.register_changed_geometries()
        super().save(*args, **kwargs)


class LocationGroupManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().select_related('category')


class LocationGroup(Location, models.Model):
    class CanReportMissing(models.TextChoices):
        DONT_OFFER = "dont_offer", _("don't offer")
        REJECT = "reject", _("offer in first step, then reject")
        SINGLE = "single", _("offer in first step, exclusive choice")
        MULTIPLE = "multiple", _("offer if nothing in the first step matches, multiple choice")

    category = models.ForeignKey(LocationGroupCategory, related_name='groups', on_delete=models.PROTECT,
                                 verbose_name=_('Category'))
    priority = models.IntegerField(default=0, db_index=True)
    hierarchy = models.IntegerField(default=0, db_index=True, verbose_name=_('hierarchy'))
    label_settings = models.ForeignKey('mapdata.LabelSettings', null=True, blank=True, on_delete=models.PROTECT,
                                       verbose_name=_('label settings'),
                                       help_text=_('unless location specifies otherwise'))
    can_report_missing = models.CharField(_('report missing location'), choices=CanReportMissing.choices,
                                          default=CanReportMissing.DONT_OFFER, max_length=16)

    description = I18nField(_('description'), plural_name='descriptions', blank=True, fallback_any=True,
                            fallback_value="", help_text=_('to aid with selection in the report form'))
    report_help_text = I18nField(_('report help text'), plural_name='report_help_texts', blank=True, fallback_any=True,
                                 fallback_value="", help_text=_('to explain the report form or rejection'))

    color = models.CharField(null=True, blank=True, max_length=32, verbose_name=_('background color'))
    in_legend = models.BooleanField(default=False, verbose_name=_('show in legend (if color set)'))
    hub_import_type = models.CharField(max_length=100, verbose_name=_('hub import type'), null=True, blank=True,
                                       unique=True,
                                       help_text=_('assign this group to imported hub locations of this type'))

    objects = LocationGroupManager()

    class Meta:
        verbose_name = _('Location Group')
        verbose_name_plural = _('Location Groups')
        default_related_name = 'locationgroups'
        ordering = ('-category__priority', '-priority')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.orig_priority = self.priority
        self.orig_hierarchy = self.hierarchy
        self.orig_category_id = self.category_id
        self.orig_color = self.color

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

    def register_changed_geometries(self, do_query=True):
        from c3nav.mapdata.models.geometry.space import SpaceGeometryMixin
        for model in get_submodels(SpecificLocation):
            query = getattr(self, model._meta.default_related_name).all()
            if do_query:
                if issubclass(model, SpaceGeometryMixin):
                    query = query.select_related('space')
            for obj in query:
                obj.register_change(force=True)

    @property
    def subtitle(self):
        result = self.category.title
        if hasattr(self, 'locations'):
            return format_lazy(_('{category_title}, {num_locations}'),
                               category_title=result,
                               num_locations=(ngettext_lazy('%(num)d location', '%(num)d locations', 'num') %
                                              {'num': len(self.locations)}))
        return result

    @cached_property
    def order(self):
        return (1, self.category.priority, self.priority)

    def save(self, *args, **kwargs):
        if self.pk and (self.orig_color != self.color or
                        self.priority != self.orig_priority or
                        self.hierarchy != self.orig_hierarchy or
                        self.category_id != self.orig_category_id):
            self.register_changed_geometries()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.register_changed_geometries()
        super().delete(*args, **kwargs)


class LocationRedirect(LocationSlug):
    target = models.ForeignKey(LocationSlug, related_name='redirects', on_delete=models.CASCADE,
                               verbose_name=_('target'))

    @property
    def target_slug(self):
        if type(self.target) is LocationSlug:
            return self.target.get_child().effective_slug
        return self.target.effective_slug

    class Meta:
        default_related_name = 'locationredirects'


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


class DynamicLocation(CustomLocationProxyMixin, SpecificLocation, models.Model):
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
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(_('name'), max_length=32)
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
        result = cache.get(cache_key, None)
        if result is None:
            result = cls.objects.filter(owner=user).exists()
            cache.set(cache_key, result, 600)
        return result

    def serialize_position(self, request=None):
        # todo: make this pretty
        custom_location = self.get_custom_location(request=request)
        if custom_location is None:
            return {
                'id': 'p:%s' % self.secret,
                'slug': 'p:%s' % self.secret,
                'available': False,
                'icon': 'my_location',
                'title': self.name,
                'subtitle': _('currently unavailable'),
            }
        from c3nav.mapdata.schemas.models import CustomLocationSchema
        result = CustomLocationSchema.model_validate(custom_location).model_dump()
        result.update({
            'available': True,
            'id': 'p:%s' % self.secret,
            'slug': 'p:%s' % self.secret,
            'icon': 'my_location',
            'title': self.name,
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
        return 'p:%s' % self.secret

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
