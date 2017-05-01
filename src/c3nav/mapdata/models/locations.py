from collections import OrderedDict

import numpy as np
from django.core.cache import cache
from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext_lazy

from c3nav.mapdata.fields import JSONField, validate_bssid_lines
from c3nav.mapdata.lastupdate import get_last_mapdata_update
from c3nav.mapdata.models import Level
from c3nav.mapdata.models.base import MapItem
from c3nav.mapdata.models.geometry import GeometryMapItemWithLevel


class Location:
    @property
    def location_id(self):
        raise NotImplementedError

    @property
    def subtitle(self):
        raise NotImplementedError

    def to_location_json(self):
        return OrderedDict((
            ('id', self.location_id),
            ('title', str(self.title)),
            ('subtitle', str(self.subtitle)),
        ))


# noinspection PyUnresolvedReferences
class LocationModelMixin(Location):
    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        result['titles'] = OrderedDict(sorted(self.titles.items()))
        return result

    @property
    def subtitle(self):
        return self._meta.verbose_name


class LocationGroup(LocationModelMixin, MapItem):
    titles = JSONField()
    can_search = models.BooleanField(default=True, verbose_name=_('can be searched'))
    can_describe = models.BooleanField(default=True, verbose_name=_('can be used to describe a position'))
    color = models.CharField(null=True, blank=True, max_length=16, verbose_name=_('background color'),
                             help_text=_('if set, has to be a valid color for svg images'))
    compiled_room = models.BooleanField(default=False, verbose_name=_('is a compiled room'))

    class Meta:
        verbose_name = _('Location Group')
        verbose_name_plural = _('Location Groups')
        default_related_name = 'locationgroups'

    @cached_property
    def location_id(self):
        return 'g:'+self.name

    def get_in_levels(self):
        last_update = get_last_mapdata_update()
        if last_update is None:
            return self._get_in_levels()

        cache_key = 'c3nav__mapdata__locationgroup__in_levels__'+last_update.isoformat()+'__'+self.name,
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

        in_levels = sorted(in_levels, key=lambda area: area.level.altitude)
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


class AreaLocation(LocationModelMixin, GeometryMapItemWithLevel):
    LOCATION_TYPES = (
        ('level', _('Level')),
        ('area', _('General Area')),
        ('room', _('Room')),
        ('roomsegment', _('Room Segment')),
        ('poi', _('Point of Interest')),
    )
    LOCATION_TYPES_ORDER = tuple(name for name, title in LOCATION_TYPES)
    ROUTING_INCLUSIONS = (
        ('default', _('Default, include if map package is unlocked')),
        ('allow_avoid', _('Included, but allow excluding')),
        ('allow_include', _('Avoided, but allow including')),
        ('needs_permission', _('Excluded, needs permission to include')),
    )

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

    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Area Location')
        verbose_name_plural = _('Area Locations')
        default_related_name = 'arealocations'

    @cached_property
    def location_id(self):
        return self.name

    def get_in_areas(self):
        last_update = get_last_mapdata_update()
        if last_update is None:
            return self._get_in_areas()

        cache_key = 'c3nav__mapdata__location__in_areas__'+last_update.isoformat()+'__'+self.name,
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
            for arealocation in AreaLocation.objects.filter(location_type=location_type, level=self.level):
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


class PointLocation(Location):
    def __init__(self, level: Level, x: int, y: int, request):
        self.level = level
        self.x = x
        self.y = y
        self.request = request

    @cached_property
    def location_id(self):
        return 'c:%s:%d:%d' % (self.level.name, self.x*100, self.y*100)

    @cached_property
    def xy(self):
        return np.array((self.x, self.y))

    @cached_property
    def description(self):
        from c3nav.routing.graph import Graph
        graph = Graph.load()
        point = graph.get_nearest_point(self.level, self.x, self.y)

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
        subtitle = '%s:%d:%d' % (self.level.name, self.x*100, self.y*100)
        if add_subtitle:
            subtitle += ' - '+add_subtitle
        return subtitle

    def to_location_json(self):
        result = super().to_location_json()
        result['level'] = self.level.name
        result['x'] = self.x
        result['y'] = self.y
        return result
