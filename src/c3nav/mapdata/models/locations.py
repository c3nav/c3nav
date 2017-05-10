from collections import OrderedDict

import numpy as np
from django.core.cache import cache
from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext_lazy

from c3nav.mapdata.fields import GeometryField, JSONField, validate_bssid_lines
from c3nav.mapdata.lastupdate import get_last_mapdata_update
from c3nav.mapdata.models.base import EditorFormMixin


class LocationSlug(models.Model):
    slug = models.SlugField(_('name'), unique=True, null=True, max_length=50)

    class Meta:
        verbose_name = _('Slug for Location')
        verbose_name_plural = _('Slugs für Locations')
        default_related_name = 'locationslugs'


class LocationModelMixin:
    pass


class Location(LocationSlug, models.Model):
    titles = JSONField(default={})
    can_search = models.BooleanField(default=True, verbose_name=_('can be searched'))
    can_describe = models.BooleanField(default=True, verbose_name=_('can be used to describe a position'))
    color = models.CharField(null=True, blank=True, max_length=16, verbose_name=_('background color'),
                             help_text=_('if set, has to be a valid color for svg images'))
    public = models.BooleanField(verbose_name=_('public'), default=True)

    class Meta:
        abstract = True

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        result['slug'] = self.slug_ptr.slug
        result['titles'] = OrderedDict(sorted(self.titles.items()))
        return result

    @property
    def subtitle(self):
        return self._meta.verbose_name


class SpecificLocation(Location, models.Model):
    groups = models.ManyToManyField('mapdata.LocationGroup', verbose_name=_('Location Groups'), blank=True)

    class Meta:
        abstract = True


class LegacyLocation:
    @property
    def location_id(self):
        raise NotImplementedError

    @property
    def subtitle(self):
        raise NotImplementedError

    def to_location_json(self):
        return OrderedDict((
            ('id', self.id),
            ('location_id', self.location_id),
            ('title', str(self.title)),
            ('subtitle', str(self.subtitle)),
        ))


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

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        return result


class AreaLocation(models.Model):
    LOCATION_TYPES = (
        ('level', _('Level')),
        ('area', _('General Area')),
        ('room', _('Room')),
        ('roomsegment', _('Room Segment')),
        ('poi', _('Point of Interest')),
    )
    LOCATION_TYPES_ORDER = tuple(name for name, title in LOCATION_TYPES)
    ROUTING_INCLUSIONS = (
        ('default', _('Default, include it is unlocked')),
        ('allow_avoid', _('Included, but allow excluding')),
        ('allow_include', _('Avoided, but allow including')),
        ('needs_permission', _('Excluded, needs permission to include')),
    )

    section = models.ForeignKey('mapdata.Section', on_delete=models.CASCADE, verbose_name=_('section'))
    geometry = GeometryField('polygon')
    slug = models.SlugField(_('Name'), unique=True, max_length=50)
    location_type = models.CharField(max_length=20, choices=LOCATION_TYPES, verbose_name=_('Location Type'))
    titles = JSONField()
    groups = models.ManyToManyField(LocationGroup, verbose_name=_('Location Groups'), blank=True)
    public = models.BooleanField(verbose_name=_('public'))

    can_search = models.BooleanField(default=True, verbose_name=_('can be searched'))
    can_describe = models.BooleanField(default=True, verbose_name=_('can be used to describe a position'))
    color = models.CharField(null=True, blank=True, max_length=16, verbose_name=_('background color'),
                             help_text=_('if set, has to be a valid color for svg images'))
    routing_inclusion = models.CharField(max_length=20, choices=ROUTING_INCLUSIONS, default='default',
                                         verbose_name=_('Routing Inclusion'))
    bssids = models.TextField(blank=True, validators=[validate_bssid_lines], verbose_name=_('BSSIDs'))

    class Meta:
        verbose_name = _('Area Location')
        verbose_name_plural = _('Area Locations')
        default_related_name = 'arealocations'

    @cached_property
    def location_id(self):
        return self.slug

    def get_in_areas(self):
        last_update = get_last_mapdata_update()
        if last_update is None:
            return self._get_in_areas()

        cache_key = 'c3nav__mapdata__location__in_areas__'+last_update.isoformat()+'__'+str(self.id),
        in_areas = cache.get(cache_key)
        if not in_areas:
            in_areas = self._get_in_areas()
            cache.set(cache_key, in_areas, 900)

        return in_areas

    def _get_in_areas(self):
        my_area = self.geometry.area

        in_areas = []
        area_location_i = self.get_sort_key(self)
        for location_type in reversed(self.LOCATION_TYPES_ORDER[:area_location_i]):
            for arealocation in AreaLocation.objects.filter(location_type=location_type, section=self.section):
                intersection_area = arealocation.geometry.intersection(self.geometry).area
                if intersection_area and intersection_area / my_area > 0.99:
                    in_areas.append(arealocation)

        return in_areas

    @property
    def subtitle(self):
        return self.get_subtitle()

    @property
    def subtitle_without_type(self):
        return self.get_subtitle()

    def get_subtitle(self):
        items = []
        items += [group.title for group in self.groups.filter(can_describe=True)]
        items += [area.title for area in self.get_in_areas() if area.can_describe]
        return ', '.join(items)

    @classmethod
    def get_sort_key(cls, arealocation):
        return cls.LOCATION_TYPES_ORDER.index(arealocation.location_type)

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        return result

    def __str__(self):
        return self.title


class PointLocation(LegacyLocation):
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
