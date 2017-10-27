from contextlib import suppress

from django.apps import apps
from django.db import models
from django.utils.translation import ugettext_lazy as _

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

    class Meta:
        verbose_name = _('Location with Slug')
        verbose_name_plural = _('Location with Slug')
        default_related_name = 'locationslugs'


class Location(LocationSlug, AccessRestrictionMixin, TitledMixin, models.Model):
    can_search = models.BooleanField(default=True, verbose_name=_('can be searched'))
    can_describe = models.BooleanField(default=True, verbose_name=_('can be used to describe a position'))

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.titles = self.titles.copy()

    def serialize(self, detailed=True, **kwargs):
        result = super().serialize(detailed=detailed, **kwargs)
        if not detailed:
            result.pop('type', None)
            result.pop('id', None)
            result.pop('slug', None)
            result.pop('target', None)
        return result

    def _serialize(self, **kwargs):
        result = super()._serialize(**kwargs)
        result['subtitle'] = self.subtitle
        result['can_search'] = self.can_search
        result['can_describe'] = self.can_search
        return result

    def get_slug(self):
        if self.slug is None:
            code = self.LOCATION_TYPE_CODES.get(self.__class__.__name__)
            if code is not None:
                return code+':'+str(self.id)
        return self.slug

    @classmethod
    def get_by_slug(cls, slug, queryset=None):
        if queryset is None:
            queryset = LocationSlug.objects.all()

        if ':' in slug:
            code, pk = slug.split(':', 1)
            model_name = cls.LOCATION_TYPE_BY_CODE.get(code)
            if model_name is None or not pk.isdigit():
                return None

            model = apps.get_model('mapdata', model_name)
            try:
                location = model.objects.get(pk=pk)
            except model.DoesNotExist:
                return None

            if location.slug is not None:
                return LocationRedirect(slug=slug, target=location)

            return location

        return queryset.filter(slug=slug).first()

    @property
    def title(self):
        if not self.titles and self.slug:
            return self._meta.verbose_name + ' ' + self.slug
        return super().title

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

    @property
    def subtitle(self):
        related_name = self.__class__._meta.default_related_name
        groups = tuple(self.groups.all())
        if groups:
            group = max((group for group in groups if getattr(group.category, 'allow_'+related_name)),
                        key=lambda group: (group.category.priority, group.priority), default=None)
            return group.title
        else:
            return str(self.__class__._meta.verbose_name)


class LocationGroupCategory(TitledMixin, models.Model):
    name = models.SlugField(_('Name'), unique=True, max_length=50)
    single = models.BooleanField(_('single selection'), default=False)
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

    def _serialize(self, **kwargs):
        result = super()._serialize(**kwargs)
        result['name'] = self.name
        result.move_to_end('name', last=False)
        result.move_to_end('id', last=False)
        return result

    def register_changed_geometries(self):
        from c3nav.mapdata.models.geometry.space import SpaceGeometryMixin
        query = self.locationgroups.all()
        for model in get_submodels(SpecificLocation):
            related_name = SpecificLocation._meta.default_related_name
            query.prefetch_related('locationgroup__'+related_name)
            if issubclass(model, SpaceGeometryMixin):
                query = query.select_related('locationgorups__'+related_name+'__space')

        for group in query:
            group.register_changed_geometries(do_query=False)

    def save(self, *args, **kwargs):
        if self.priority != self.orig_priority:
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
        self.orig_category = self.category
        self.orig_color = self.color

    def _serialize(self, **kwargs):
        result = super()._serialize(**kwargs)
        result['category'] = self.category_id
        result['color'] = self.color
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
            query = getattr(self, SpecificLocation._meta.default_related_name).objects.all()
            if do_query:
                if issubclass(model, SpaceGeometryMixin):
                    query = query.select_related('space')
            for obj in query:
                obj.register_change(force=True)

    def save(self, *args, **kwargs):
        if self.orig_color != self.color or self.priority != self.orig_priority or self.category != self.orig_category:
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
