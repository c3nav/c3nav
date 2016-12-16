import re
from collections import OrderedDict

from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.fields import JSONField
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

    class Meta:
        verbose_name = _('Location Group')
        verbose_name_plural = _('Location Groups')
        default_related_name = 'locationgroups'

    @cached_property
    def location_id(self):
        return 'g:'+self.name


class AreaLocation(LocationModelMixin, GeometryMapItemWithLevel):
    titles = JSONField()
    groups = models.ManyToManyField(LocationGroup, verbose_name=_('Location Groups'), blank=True)

    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Area Location')
        verbose_name_plural = _('Area Locations')
        default_related_name = 'arealocations'

    @cached_property
    def location_id(self):
        return self.name

    @classmethod
    def fromfile(cls, data, file_path):
        kwargs = super().fromfile(data, file_path)

        groups = data.get('groups', [])
        if not isinstance(groups, list):
            raise TypeError('groups has to be a list')
        kwargs['groups'] = groups

        return kwargs

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        result['groups'] = tuple(self.groups.all().order_by('name').values_list('name', flat=True))
        return result

    def tofile(self):
        result = super().tofile()
        result['groups'] = sorted(self.groups.all().order_by('name').values_list('name', flat=True))
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
