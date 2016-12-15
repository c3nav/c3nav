import re
from abc import ABC, abstractmethod
from collections import OrderedDict

from django.core.cache import cache

from c3nav.mapdata.lastupdate import get_last_mapdata_update
from c3nav.mapdata.models import AreaOfInterest, GroupOfInterest, Level
from c3nav.mapdata.permissions import filter_queryset_by_package_access
from c3nav.mapdata.utils.cache import get_levels_cached


def get_location(request, name):
    match = re.match('^c:(?P<level>[a-z0-9-_]+):(?P<x>[0-9]+):(?P<y>[0-9]+)$', name)
    if match:
        levels = get_levels_cached()
        level = levels.get(match.group('level'))
        if level is None:
            return None
        return PointLocation.from_cache(level=level, x=int(match.group('x')), y=int(match.group('y')))

    if name.startswith('g:'):
        group = filter_queryset_by_package_access(request, GroupOfInterest.objects.filter(name=name[2:])).first()
        if group is None:
            return None
        return GroupOfInterestLocation(group)

    area = filter_queryset_by_package_access(request, AreaOfInterest.objects.filter(name=name)).first()
    if area is None:
        return None
    return AreaOfInterestLocation(area)


class Location(ABC):
    @classmethod
    def _from_cache(cls, cache_key, *args, **kwargs):
        last_update = get_last_mapdata_update()
        if last_update is None:
            return cls(*args, **kwargs)

        cache_key = 'c3nav__locations__%s__%s__%s' % (last_update.isoformat(), cls.__name__, cache_key)
        obj = cache.get(cache_key)
        if not obj:
            obj = cls(*args, **kwargs)
            cache.set(cache_key, obj, 300)
        return obj

    def __init__(self, name):
        self.name = name

    @property
    @abstractmethod
    def title(self) -> str:
        pass

    @property
    @abstractmethod
    def subtitle(self) -> str:
        pass

    def to_json(self):
        return OrderedDict((
            ('name', self.name),
            ('title', self.title),
            ('subtitle', self.subtitle),
        ))


class AreaOfInterestLocation(Location):
    @classmethod
    def from_cache(cls, area: AreaOfInterest):
        return cls._from_cache(area.name, area)

    def __init__(self, area: AreaOfInterest):
        super().__init__(name=area.name)
        self.area = area

    @property
    def title(self) -> str:
        return self.area.title

    @property
    def subtitle(self) -> str:
        return 'Location Group'


class GroupOfInterestLocation(Location):
    @classmethod
    def from_cache(cls, group: GroupOfInterest):
        return cls._from_cache(group.name, group)

    def __init__(self, group: GroupOfInterest):
        super().__init__(name=group.name)
        self.group = group

    @property
    def title(self) -> str:
        return self.group.title

    @property
    def subtitle(self) -> str:
        return 'Location'


class PointLocation(Location):
    @classmethod
    def from_cache(cls, level: Level, x: int, y: int):
        return cls._from_cache('%s:%d:%d' % (level.name, x, y), level, x, y)

    def __init__(self, level: Level, x: int, y: int):
        super().__init__(name='c:%s:%d:%d' % (level.name, x, y))
        self.level = level
        self.x = x
        self.y = y

    @property
    def title(self) -> str:
        return 'Custom location'

    @property
    def subtitle(self) -> str:
        return 'Coordinates'

    def to_json(self):
        result = super().to_json()
        result['level'] = self.level.name
        result['x'] = self.x
        result['y'] = self.y
        return result
