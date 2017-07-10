from contextlib import suppress

from django.apps import apps
from django.db import models
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.models.base import SerializableMixin, TitledMixin
from c3nav.mapdata.utils.models import get_submodels


class LocationSlugManager(models.Manager):
    def get_queryset(self):
        result = super().get_queryset()
        if self.model == LocationSlug:
            result = result.select_related(*(model._meta.default_related_name
                                             for model in get_submodels(Location)+[LocationRedirect]))
        return result


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


class Location(LocationSlug, TitledMixin, models.Model):
    can_search = models.BooleanField(default=True, verbose_name=_('can be searched'))
    can_describe = models.BooleanField(default=True, verbose_name=_('can be used to describe a position'))
    color = models.CharField(null=True, blank=True, max_length=16, verbose_name=_('background color'))
    public = models.BooleanField(verbose_name=_('public'), default=True)

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
        result['can_search'] = self.can_search
        result['can_describe'] = self.can_search
        result['color'] = self.color
        result['public'] = self.public
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

    def get_color(self, instance=None):
        if self.color:
            return self.color
        # dont filter in the query here so prefetch_related works
        if instance is None:
            instance = self
        groups = [group for group in instance.groups.all() if group.color]
        if not groups:
            return None
        for group in groups:
            if group.compiled_area:
                return group.color
        for group in groups:
            if group.compiled_room:
                return group.color
        return groups[0].color


class SpecificLocation(Location, models.Model):
    groups = models.ManyToManyField('mapdata.LocationGroup', verbose_name=_('Location Groups'), blank=True)

    class Meta:
        abstract = True

    def _serialize(self, detailed=True, **kwargs):
        result = super()._serialize(detailed=detailed, **kwargs)
        if detailed:
            groups = {}
            for group in self.groups.all():
                groups.setdefault(group.category.name, []).append(group.pk)
            result['groups'] = groups
        return result


class LocationGroupCategory(TitledMixin, models.Model):
    name = models.SlugField(_('Name'), unique=True, max_length=50)
    single = models.BooleanField(_('single selection'), default=False)
    allow_levels = models.BooleanField(_('allow levels'), db_index=True, default=True)
    allow_spaces = models.BooleanField(_('allow spaces'), db_index=True, default=True)
    allow_areas = models.BooleanField(_('allow areas'), db_index=True, default=True)
    allow_pois = models.BooleanField(_('allow pois'), db_index=True, default=True)
    priority = models.IntegerField(default=0, db_index=True)

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


class LocationGroup(Location, models.Model):
    category = models.ForeignKey(LocationGroupCategory, related_name='groups', on_delete=models.PROTECT,
                                 verbose_name=_('Category'))
    compiled_room = models.BooleanField(default=False, verbose_name=_('is a compiled room'))
    compiled_area = models.BooleanField(default=False, verbose_name=_('is a compiled area'))
    priority = models.IntegerField(default=0, db_index=True)

    class Meta:
        verbose_name = _('Location Group')
        verbose_name_plural = _('Location Groups')
        default_related_name = 'locationgroups'
        ordering = ('-priority',)

    def _serialize(self, **kwargs):
        result = super()._serialize(**kwargs)
        result['category'] = self.category_id
        result['compiled_room'] = self.compiled_room
        result['compiled_area'] = self.compiled_area
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
        if self.compiled_room:
            attributes.append(_('comp. room'))
        if self.compiled_area:
            attributes.append(_('comp. area'))
        return self.title + ' ('+', '.join(str(s) for s in attributes)+')'


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
