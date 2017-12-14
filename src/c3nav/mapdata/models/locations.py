from collections import OrderedDict
from contextlib import suppress
from operator import attrgetter

from django.db import models
from django.db.models import Prefetch
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.text import format_lazy
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext_lazy

from c3nav.mapdata.fields import I18nField
from c3nav.mapdata.models.access import AccessRestrictionMixin
from c3nav.mapdata.models.base import SerializableMixin, TitledMixin
from c3nav.mapdata.utils.models import get_submodels


class LocationSlugManager(models.Manager):
    def get_queryset(self):
        result = super().get_queryset()
        if self.model == LocationSlug:
            result = result.select_related(*(model._meta.default_related_name
                                             for model in get_submodels(Location)+[LocationRedirect]))
        return result

    def select_related_target(self):
        if self.model != LocationSlug:
            raise TypeError
        qs = self.get_queryset()
        qs = qs.select_related('redirect__target', *('redirect__target__'+model._meta.default_related_name
                                                     for model in get_submodels(Location) + [LocationRedirect]))
        return qs


class LocationSlug(SerializableMixin, models.Model):
    LOCATION_TYPE_CODES = {
        'Level': 'l',
        'Space': 's',
        'Area': 'a',
        'POI': 'p',
        'LocationGroup': 'g'
    }
    LOCATION_TYPE_BY_CODE = {code: model_name for model_name, code in LOCATION_TYPE_CODES.items()}
    slug = models.SlugField(_('Slug'), unique=True, null=True, blank=True, max_length=50)

    objects = LocationSlugManager()

    def get_child(self):
        for model in get_submodels(Location)+[LocationRedirect]:
            with suppress(AttributeError):
                return getattr(self, model._meta.default_related_name)
        return None

    def get_slug(self):
        return self.slug

    def _serialize(self, **kwargs):
        result = super()._serialize(**kwargs)
        result['slug'] = self.get_slug()
        return result

    def details_display(self):
        result = super().details_display()
        result['display'].insert(2, (_('Slug'), str(self.get_slug())))
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

    class Meta:
        abstract = True

    def serialize(self, detailed=True, describe_only=False, **kwargs):
        result = super().serialize(detailed=detailed, **kwargs)
        if not detailed:
            if describe_only and not self.can_describe:
                fields = ('id', 'on_top_of')
            else:
                fields = ('id', 'type', 'slug', 'title', 'subtitle', 'point', 'bounds', 'locations', 'on_top_of')
            result = OrderedDict(((name, result[name]) for name in fields if name in result))
        return result

    def _serialize(self, **kwargs):
        result = super()._serialize(**kwargs)
        result['subtitle'] = str(self.subtitle)
        result['can_search'] = self.can_search
        result['can_describe'] = self.can_search
        return result

    def details_display(self):
        result = super().details_display()
        result['display'].extend([
            (_('searchable'), _('Yes') if self.can_search else _('No')),
            (_('can describe'), _('Yes') if self.can_describe else _('No'))
        ])
        return result

    def get_slug(self):
        if self.slug is None:
            code = self.LOCATION_TYPE_CODES.get(self.__class__.__name__)
            if code is not None:
                return code+':'+str(self.id)
        return self.slug

    @property
    def subtitle(self):
        return ''

    def get_color(self, instance=None):
        # dont filter in the query here so prefetch_related works
        if instance is None:
            instance = self
        for group in instance.groups.all():
            if group.color and getattr(group.category, 'allow_'+self.__class__._meta.default_related_name):
                return group.color
        return None


class SpecificLocation(Location, models.Model):
    groups = models.ManyToManyField('mapdata.LocationGroup', verbose_name=_('Location Groups'), blank=True)

    class Meta:
        abstract = True

    def _serialize(self, detailed=True, **kwargs):
        result = super()._serialize(detailed=detailed, **kwargs)
        if detailed:
            groups = {}
            for group in self.groups.all():
                groups.setdefault(group.category, []).append(group.pk)
            groups = {category.name: (items[0] if items else None) if category.single else items
                      for category, items in groups.items()
                      if getattr(category, 'allow_'+self.__class__._meta.default_related_name)}
            result['groups'] = groups
        return result

    def details_display(self):
        result = super().details_display()

        groupcategories = {}
        for group in self.groups.all():
            groupcategories.setdefault(group.category, []).append(group)

        for category, groups in sorted(groupcategories.items(), key=lambda item: item[0].priority):
            result['display'].insert(3, (
                category.title,
                tuple({
                    'id': group.pk,
                    'slug': group.get_slug(),
                    'title': group.title,
                    'can_search': group.can_search,
                } for group in sorted(groups, key=attrgetter('priority'), reverse=True))
            ))

        return result

    @property
    def subtitle(self):
        groups = tuple(self.groups.all() if 'group' in getattr(self, '_prefetched_objects_cache', ()) else ())
        return groups[0].title if groups else self.__class__._meta.verbose_name

    @cached_property
    def order(self):
        groups = tuple(self.groups.all())
        if not groups:
            return (0, 0, 0)
        return (0, groups[0].category.priority, groups[0].priority)


class LocationGroupCategory(SerializableMixin, models.Model):
    name = models.SlugField(_('Name'), unique=True, max_length=50)
    single = models.BooleanField(_('single selection'), default=False)
    title = I18nField(_('Title'), plural_name='titles', fallback_any=True)
    title_plural = I18nField(_('Title (Plural)'), plural_name='titles_plural', fallback_any=True)
    allow_levels = models.BooleanField(_('allow levels'), db_index=True, default=True)
    allow_spaces = models.BooleanField(_('allow spaces'), db_index=True, default=True)
    allow_areas = models.BooleanField(_('allow areas'), db_index=True, default=True)
    allow_pois = models.BooleanField(_('allow pois'), db_index=True, default=True)
    priority = models.IntegerField(default=0, db_index=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.orig_priority = self.priority

    class Meta:
        verbose_name = _('Location Group Category')
        verbose_name_plural = _('Location Group Categories')
        default_related_name = 'locationgroupcategories'
        ordering = ('-priority', )

    def _serialize(self, detailed=True, **kwargs):
        result = super()._serialize(detailed=detailed, **kwargs)
        result['name'] = self.name
        if detailed:
            result['titles'] = self.titles
        result['title'] = self.title
        return result

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
    category = models.ForeignKey(LocationGroupCategory, related_name='groups', on_delete=models.PROTECT,
                                 verbose_name=_('Category'))
    priority = models.IntegerField(default=0, db_index=True)
    color = models.CharField(null=True, blank=True, max_length=32, verbose_name=_('background color'))

    objects = LocationGroupManager()

    class Meta:
        verbose_name = _('Location Group')
        verbose_name_plural = _('Location Groups')
        default_related_name = 'locationgroups'
        ordering = ('-category__priority', '-priority')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.orig_priority = self.priority
        self.orig_category_id = self.category_id
        self.orig_color = self.color

    def _serialize(self, simple_geometry=False, **kwargs):
        result = super()._serialize(simple_geometry=simple_geometry, **kwargs)
        result['category'] = self.category_id
        result['color'] = self.color
        if simple_geometry:
            result['locations'] = tuple(obj.pk for obj in getattr(self, 'locations', ()))
        return result

    def details_display(self):
        result = super().details_display()
        result['display'].insert(3, (_('Category'), self.category.title))
        result['display'].extend([
            (_('color'), self.color),
            (_('priority'), self.priority),
        ])
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
                               num_locations=(ungettext_lazy('%(num)d location', '%(num)d locations', 'num') %
                                              {'num': len(self.locations)}))
        return result

    @cached_property
    def order(self):
        return (1, self.category.priority, self.priority)

    def save(self, *args, **kwargs):
        if self.pk and (self.orig_color != self.color or
                        self.priority != self.orig_priority or
                        self.category_id != self.orig_category_id):
            self.register_changed_geometries()
        super().save(*args, **kwargs)


class LocationRedirect(LocationSlug):
    target = models.ForeignKey(LocationSlug, related_name='redirects', on_delete=models.CASCADE,
                               verbose_name=_('target'))

    def _serialize(self, with_type=True, **kwargs):
        result = super()._serialize(with_type=with_type, **kwargs)
        if type(self.target) == LocationSlug:
            result['target'] = self.target.get_child().slug
        else:
            result['target'] = self.target.slug
        if with_type:
            result['type'] = 'redirect'
        result.pop('id')
        return result

    class Meta:
        default_related_name = 'redirect'
