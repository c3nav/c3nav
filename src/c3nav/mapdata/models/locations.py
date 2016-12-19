import re
from collections import OrderedDict

from django.core.cache import cache
from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.fields import JSONField
from c3nav.mapdata.lastupdate import get_last_mapdata_update
from c3nav.mapdata.models import Level
from c3nav.mapdata.models.base import MapItem
from c3nav.mapdata.models.geometry import GeometryMapItemWithLevel
from c3nav.mapdata.permissions import filter_queryset_by_package_access
from c3nav.mapdata.utils.cache import get_levels_cached


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

    @classmethod
    def fromfile(cls, data, file_path):
        kwargs = super().fromfile(data, file_path)

        if 'titles' not in data:
            raise ValueError('missing titles.')
        titles = data['titles']
        if not isinstance(titles, dict):
            raise ValueError('Invalid titles format.')
        if any(not isinstance(lang, str) for lang in titles.keys()):
            raise ValueError('titles: All languages have to be strings.')
        if any(not isinstance(title, str) for title in titles.values()):
            raise ValueError('titles: All titles have to be strings.')
        if any(not title for title in titles.values()):
            raise ValueError('titles: Titles must not be empty strings.')
        kwargs['titles'] = titles
        return kwargs

    def tofile(self):
        result = super().tofile()
        result['titles'] = OrderedDict(sorted(self.titles.items()))
        return result

    @property
    def subtitle(self):
        return self._meta.verbose_name


class LocationGroup(LocationModelMixin, MapItem):
    titles = JSONField()
    can_search = models.BooleanField(default=True, verbose_name=_('can be searched'))

    class Meta:
        verbose_name = _('Location Group')
        verbose_name_plural = _('Location Groups')
        default_related_name = 'locationgroups'

    @cached_property
    def location_id(self):
        return 'g:'+self.name

    @classmethod
    def fromfile(cls, data, file_path):
        kwargs = super().fromfile(data, file_path)

        if 'can_search' not in data:
            raise ValueError('Missing can_search')
        can_search = data['can_search']
        if not isinstance(can_search, bool):
            raise ValueError('can_search has to be boolean!')
        kwargs['can_search'] = can_search

        return kwargs

    def tofile(self):
        result = super().tofile()
        result['can_search'] = self.can_search
        return result

    def __str__(self):
        return self.title


class AreaLocation(LocationModelMixin, GeometryMapItemWithLevel):
    LOCATION_TYPES = (
        ('level', _('Level')),
        ('area', _('General Area')),
        ('room', _('Room')),
        ('roomsegment', _('Room Segment')),
        ('poi', _('Point of Interest')),
    )
    LOCATION_TYPES_ORDER = tuple(name for name, title in LOCATION_TYPES)

    location_type = models.CharField(max_length=20, verbose_name=_('Location Type'), choices=LOCATION_TYPES)
    titles = JSONField()
    can_search = models.BooleanField(default=True, verbose_name=_('can be searched'))
    can_describe = models.BooleanField(default=True, verbose_name=_('can be used to describe a position'))
    groups = models.ManyToManyField(LocationGroup, verbose_name=_('Location Groups'), blank=True)

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

        cache_key = 'c3nav__mapdata__location__in__areas__'+last_update.isoformat()+'__'+self.name,
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

    def get_subtitle(self):
        items = [self.get_location_type_display()]
        items += [area.title for area in self.get_in_areas()]
        return ', '.join(items)

    @classmethod
    def get_sort_key(cls, arealocation):
        return cls.LOCATION_TYPES_ORDER.index(arealocation.location_type)

    @classmethod
    def fromfile(cls, data, file_path):
        kwargs = super().fromfile(data, file_path)

        groups = data.get('groups', [])
        if not isinstance(groups, list):
            raise TypeError('groups has to be a list')
        kwargs['groups'] = groups

        if 'location_type' not in data:
            raise ValueError('Missing location type')
        location_type = data['location_type']
        if location_type not in dict(cls.LOCATION_TYPES):
            raise ValueError('Invalid location type')
        kwargs['location_tyoe'] = location_type

        if 'can_search' not in data:
            raise ValueError('Missing can_search')
        can_search = data['can_search']
        if not isinstance(can_search, bool):
            raise ValueError('can_search has to be boolean!')
        kwargs['can_search'] = can_search

        if 'can_describe' not in data:
            raise ValueError('Missing can_describe')
        can_describe = data['can_describe']
        if not isinstance(can_describe, bool):
            raise ValueError('can_describe has to be boolean!')
        kwargs['can_describe'] = can_describe

        return kwargs

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        result['groups'] = tuple(self.groups.all().order_by('name').values_list('name', flat=True))
        return result

    def tofile(self):
        result = super().tofile()
        result['groups'] = sorted(self.groups.all().order_by('name').values_list('name', flat=True))
        result['location_type'] = self.location_type
        result['can_search'] = self.can_search
        result['can_describe'] = self.can_describe
        result.move_to_end('geometry')
        return result

    def __str__(self):
        return self.title


def get_location(request, name):
    match = re.match('^c:(?P<level>[a-z0-9-_]+):(?P<x>[0-9]+):(?P<y>[0-9]+)$', name)
    if match:
        levels = get_levels_cached()
        level = levels.get(match.group('level'))
        if level is None:
            return None
        return PointLocation(level=level, x=int(match.group('x')), y=int(match.group('y')))

    if name.startswith('g:'):
        return filter_queryset_by_package_access(request, LocationGroup.objects.filter(name=name[2:])).first()

    return filter_queryset_by_package_access(request, AreaLocation.objects.filter(name=name)).first()


class PointLocation(Location):
    def __init__(self, level: Level, x: int, y: int):
        self.level = level
        self.x = x
        self.y = y

    @cached_property
    def location_id(self):
        return 'c:%s:%d:%d' % (self.level.name, self.x, self.y)

    @property
    def title(self) -> str:
        return 'Custom location'

    @property
    def subtitle(self) -> str:
        return 'Coordinates'

    def to_location_json(self):
        result = super().to_location_json()
        result['level'] = self.level.name
        result['x'] = self.x
        result['y'] = self.y
        return result
