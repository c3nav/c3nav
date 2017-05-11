import numpy as np
from django.apps import apps
from django.core.cache import cache
from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import get_language, ungettext_lazy

from c3nav.mapdata.fields import JSONField
from c3nav.mapdata.lastupdate import get_last_mapdata_update
from c3nav.mapdata.models.base import EditorFormMixin, SerializableMixin

LOCATION_MODELS = []


class LocationSlug(SerializableMixin, models.Model):
    LOCATION_TYPE_CODES = {
        'Section': 'se',
        'Space': 'sp',
        'Area': 'a',
        'Point': 'p',
        'LocationGroup': 'g'
    }
    LOCATION_TYPE_BY_CODE = {code: model_name for model_name, code in LOCATION_TYPE_CODES.items()}
    slug = models.SlugField(_('name'), unique=True, null=True, max_length=50)

    def get_child(self):
        # todo: cache this
        for model in LOCATION_MODELS+[LocationRedirect]:
            try:
                return getattr(self, model._meta.default_related_name)
            except AttributeError:
                pass
        return None

    class Meta:
        verbose_name = _('Slug for Location')
        verbose_name_plural = _('Slugs für Locations')
        default_related_name = 'locationslugs'


class LocationModelMixin:
    pass


class Location(LocationSlug, EditorFormMixin, models.Model):
    titles = JSONField(default={})
    can_search = models.BooleanField(default=True, verbose_name=_('can be searched'))
    can_describe = models.BooleanField(default=True, verbose_name=_('can be used to describe a position'))
    color = models.CharField(null=True, blank=True, max_length=16, verbose_name=_('background color'),
                             help_text=_('if set, has to be a valid color for svg images'))
    public = models.BooleanField(verbose_name=_('public'), default=True)

    class Meta:
        abstract = True

    def _serialize(self, **kwargs):
        result = super()._serialize(**kwargs)
        result['slug'] = self.get_slug()
        result['titles'] = self.titles
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
        if not hasattr(self, 'titles'):
            return self.name
        lang = get_language()
        if lang in self.titles:
            return self.titles[lang]
        return next(iter(self.titles.values())) if self.titles else self.name

    @property
    def subtitle(self):
        return self._meta.verbose_name


class SpecificLocation(Location, models.Model):
    groups = models.ManyToManyField('mapdata.LocationGroup', verbose_name=_('Location Groups'), blank=True)

    class Meta:
        abstract = True

    def _serialize(self, **kwargs):
        result = super()._serialize(**kwargs)
        result['groups'] = list(self.groups.values_list('id', flat=True))
        return result


class LocationGroup(Location, EditorFormMixin, models.Model):
    compiled_room = models.BooleanField(default=False, verbose_name=_('is a compiled room'))
    compiled_area = models.BooleanField(default=False, verbose_name=_('is a compiled area'))

    class Meta:
        verbose_name = _('Location Group')
        verbose_name_plural = _('Location Groups')
        default_related_name = 'locationgroups'

    @cached_property
    def location_id(self):
        return 'g:'+self.slug

    def get_in_levels(self):
        last_update = get_last_mapdata_update()
        if last_update is None:
            return self._get_in_levels()

        cache_key = 'c3nav__mapdata__locationgroup__in_levels__'+last_update.isoformat()+'__'+str(self.id),
        in_levels = cache.get(cache_key)
        if not in_levels:
            in_levels = self._get_in_levels()
            cache.set(cache_key, in_levels, 900)

        return in_levels

    def _get_in_levels(self):
        level_ids = set()
        in_levels = []
        for arealocation in self.arealocations.all():
            for area in arealocation.get_in_areas():
                if area.location_type == 'level' and area.id not in level_ids:
                    level_ids.add(area.id)
                    in_levels.append(area)

        in_levels = sorted(in_levels, key=lambda area: area.section.altitude)
        return in_levels

    @property
    def subtitle(self):
        if self.compiled_room:
            return ', '.join(area.title for area in self.get_in_levels())
        return ungettext_lazy('%d location', '%d locations') % self.arealocations.count()

    def __str__(self):
        return self.title

    def _serialize(self, **kwargs):
        result = super()._serialize(**kwargs)
        result['compiled_room'] = self.compiled_room
        result['compiled_area'] = self.compiled_area
        return result


class LocationRedirect(LocationSlug):
    target = models.ForeignKey(LocationSlug, verbose_name=_('target'), related_name='redirects')

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


class PointLocation:
    def __init__(self, section: 'Section', x: int, y: int, request):
        self.section = section
        self.x = x
        self.y = y
        self.request = request

    @cached_property
    def location_id(self):
        return 'c:%d:%d:%d' % (self.section.id, self.x * 100, self.y * 100)

    @cached_property
    def xy(self):
        return np.array((self.x, self.y))

    @cached_property
    def description(self):
        from c3nav.routing.graph import Graph
        graph = Graph.load()
        point = graph.get_nearest_point(self.section, self.x, self.y)

        if point is None or (':nonpublic' in point.arealocations and not self.request.c3nav_full_access and
                             not len(set(self.request.c3nav_access_list) & set(point.arealocations))):
            return _('Unreachable Coordinates'), ''

        AreaLocation = None
        locations = sorted(AreaLocation.objects.filter(name__in=point.arealocations, can_describe=True),
                           key=AreaLocation.get_sort_key, reverse=True)

        if not locations:
            return _('Coordinates'), ''

        location = locations[0]
        if location.contains(self.x, self.y):
            return (_('Coordinates in %(location)s') % {'location': location.title}), location.subtitle_without_type
        else:
            return (_('Coordinates near %(location)s') % {'location': location.title}), location.subtitle_without_type

    @property
    def title(self) -> str:
        return self.description[0]

    @property
    def subtitle(self) -> str:
        add_subtitle = self.description[1]
        subtitle = '%s:%d:%d' % (self.section.name, self.x * 100, self.y * 100)
        if add_subtitle:
            subtitle += ' - '+add_subtitle
        return subtitle

    def to_location_json(self):
        result = super().to_location_json()
        result['section'] = self.section.id
        result['x'] = self.x
        result['y'] = self.y
        return result
