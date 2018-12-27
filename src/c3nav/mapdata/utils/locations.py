import math
import operator
import re
from collections import OrderedDict
from functools import reduce
from itertools import chain
from typing import List, Mapping, Optional

from django.apps import apps
from django.core.cache import cache
from django.db.models import Prefetch, Q
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _
from shapely.ops import cascaded_union

from c3nav.mapdata.grid import grid
from c3nav.mapdata.models import Level, Location, LocationGroup, MapUpdate
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.models.geometry.base import GeometryMixin
from c3nav.mapdata.models.geometry.level import LevelGeometryMixin, Space
from c3nav.mapdata.models.geometry.space import SpaceGeometryMixin
from c3nav.mapdata.models.locations import LocationRedirect, LocationSlug, SpecificLocation
from c3nav.mapdata.utils.models import get_submodels


def locations_for_request(request) -> Mapping[int, LocationSlug]:
    cache_key = 'mapdata:locations:%s' % AccessPermission.cache_key_for_request(request)
    locations = cache.get(cache_key, None)
    if locations is not None:
        return locations

    locations = LocationSlug.objects.all().order_by('id')

    conditions = []
    for model in get_submodels(Location):
        related_name = model._meta.default_related_name
        condition = Q(**{related_name + '__isnull': False})
        # noinspection PyUnresolvedReferences
        condition &= model.q_for_request(request, prefix=related_name + '__')
        conditions.append(condition)
    locations = locations.filter(reduce(operator.or_, conditions))
    locations.select_related('redirect', 'locationgroups__category')

    # prefetch locationgroups
    base_qs = LocationGroup.qs_for_request(request).select_related('category')
    for model in get_submodels(SpecificLocation):
        locations = locations.prefetch_related(Prefetch(model._meta.default_related_name + '__groups',
                                                        queryset=base_qs))

    locations = {obj.pk: obj.get_child() for obj in locations}

    # add locations to groups
    locationgroups = {pk: obj for pk, obj in locations.items() if isinstance(obj, LocationGroup)}
    for group in locationgroups.values():
        group.locations = []
    for obj in locations.values():
        if not isinstance(obj, SpecificLocation):
            continue
        for group in obj.groups.all():
            group = locationgroups.get(group.pk, None)
            if group is not None:
                group.locations.append(obj)

    # add levels to spaces
    remove_pks = set()
    levels = {pk: obj for pk, obj in locations.items() if isinstance(obj, Level)}
    for pk, obj in locations.items():
        if isinstance(obj, LevelGeometryMixin):
            level = levels.get(obj.level_id, None)
            if level is None:
                remove_pks.add(pk)
                continue
            obj._level_cache = level

    # hide spaces on hidden levels
    for pk in remove_pks:
        locations.pop(pk)

    # add spaces to areas and POIs
    remove_pks = set()
    spaces = {pk: obj for pk, obj in locations.items() if isinstance(obj, Space)}
    for pk, obj in locations.items():
        if isinstance(obj, SpaceGeometryMixin):
            space = spaces.get(obj.space_id, None)
            if space is None:
                remove_pks.add(pk)
                continue
            obj._space_cache = space

    # hide locations on hidden spaces
    for pk in remove_pks:
        locations.pop(pk)

    # add targets to LocationRedirects
    levels = {pk: obj for pk, obj in locations.items() if isinstance(obj, Level)}
    for obj in locations.values():
        if isinstance(obj, LocationRedirect):
            obj._target_cache = locations.get(obj.target_id, None)

    # apply better space geometries
    for pk, geometry in get_better_space_geometries().items():
        if pk in locations:
            locations[pk].geometry = geometry

    # precache cached properties
    for obj in locations.values():
        # noinspection PyStatementEffect
        obj.subtitle, obj.order
        if isinstance(obj, GeometryMixin):
            # noinspection PyStatementEffect
            obj.point

    cache.set(cache_key, locations, 1800)

    return locations


def get_better_space_geometries():
    # change space geometries for better representative points
    cache_key = 'mapdata:better_space_geometries:%s' % MapUpdate.current_cache_key()
    result = cache.get(cache_key, None)
    if result is not None:
        return result

    result = {}
    for space in Space.objects.prefetch_related('columns', 'holes'):
        geometry = space.geometry.difference(
            cascaded_union(tuple(obj.geometry for obj in chain(space.columns.all(), space.holes.all())))
        )
        if not geometry.is_empty:
            result[space.pk] = geometry

    cache.set(cache_key, result, 1800)

    return result


def visible_locations_for_request(request) -> Mapping[int, Location]:
    cache_key = 'mapdata:locations:real:%s' % AccessPermission.cache_key_for_request(request)
    locations = cache.get(cache_key, None)
    if locations is not None:
        return locations

    locations = {pk: location for pk, location in locations_for_request(request).items()
                 if not isinstance(location, LocationRedirect) and (location.can_search or location.can_describe)}

    cache.set(cache_key, locations, 1800)

    return locations


def searchable_locations_for_request(request) -> List[Location]:
    cache_key = 'mapdata:locations:searchable:%s' % AccessPermission.cache_key_for_request(request)
    locations = cache.get(cache_key, None)
    if locations is not None:
        return locations

    locations = (location for location in locations_for_request(request).values() if isinstance(location, Location))
    locations = tuple(location for location in locations if location.can_search)

    locations = sorted(locations, key=operator.attrgetter('order'), reverse=True)

    cache.set(cache_key, locations, 1800)

    return locations


def locations_by_slug_for_request(request) -> Mapping[str, LocationSlug]:
    cache_key = 'mapdata:locations:by_slug:%s' % AccessPermission.cache_key_for_request(request)
    locations = cache.get(cache_key, None)
    if locations is not None:
        return locations

    locations = {location.slug: location for location in locations_for_request(request).values() if location.slug}

    cache.set(cache_key, locations, 1800)

    return locations


def levels_by_short_label_for_request(request) -> Mapping[str, Level]:
    cache_key = 'mapdata:levels:by_short_label:%s' % AccessPermission.cache_key_for_request(request)
    levels = cache.get(cache_key, None)
    if levels is not None:
        return levels

    levels = OrderedDict(
        (level.short_label, level)
        for level in Level.qs_for_request(request).filter(on_top_of_id__isnull=True).order_by('base_altitude')
    )

    cache.set(cache_key, levels, 1800)

    return levels


def get_location_by_id_for_request(pk, request):
    if isinstance(pk, str):
        if pk.isdigit():
            pk = int(pk)
        else:
            return get_custom_location_for_request(pk, request)
    return locations_for_request(request).get(pk)


def get_location_by_slug_for_request(slug: str, request) -> Optional[LocationSlug]:
    cache_key = 'mapdata:location:by_slug:%s:%s' % (AccessPermission.cache_key_for_request(request), slug)
    location = cache.get(cache_key, None)
    if location is not None:
        return location

    if slug.startswith('c:'):
        location = get_custom_location_for_request(slug, request)
        if location is None:
            return None
    elif ':' in slug:
        code, pk = slug.split(':', 1)
        model_name = LocationSlug.LOCATION_TYPE_BY_CODE.get(code)
        if model_name is None or not pk.isdigit():
            return None

        model = apps.get_model('mapdata', model_name)
        location = locations_for_request(request).get(int(pk), None)

        if location is None or not isinstance(location, model):
            return None

        if location.slug is not None:
            location = LocationRedirect(slug=slug, target=location)
    else:
        location = locations_by_slug_for_request(request).get(slug, None)

    cache.set(cache_key, location, 1800)

    return location


def get_custom_location_for_request(slug: str, request):
    match = re.match(r'^c:(?P<level>[a-z0-9-_]+):(?P<x>-?\d+(\.\d+)?):(?P<y>-?\d+(\.\d+)?)$', slug)
    if match is None:
        return None
    level = levels_by_short_label_for_request(request).get(match.group('level'))
    if not isinstance(level, Level):
        return None
    return CustomLocation(level, float(match.group('x')), float(match.group('y')),
                          AccessPermission.get_for_request(request))


class CustomLocation:
    can_search = True
    can_describe = True
    access_restriction_id = None

    def __init__(self, level, x, y, permissions, icon='pin_drop'):
        x = round(x, 2)
        y = round(y, 2)
        self.pk = 'c:%s:%s:%s' % (level.short_label, x, y)
        self.permissions = permissions
        self.level = level
        self.x = x
        self.y = y
        self.icon = icon

    @property
    def serialized_geometry(self):
        return {
            'type': 'Point',
            'coordinates': (self.x, self.y)
        }

    def serialize(self, include_type=False, simple_geometry=False, geometry=True, **kwargs):
        result = OrderedDict((
            ('id', self.pk),
            ('slug', self.pk),
            ('icon', self.icon),
            ('title', self.title),
            ('subtitle', self.subtitle),
            ('level', self.level.pk),
            ('space', self.space.pk if self.space else None),
            ('areas', tuple(area.pk for area in self.areas)),
            ('grid_square', self.grid_square),
            ('near_area', self.near_area.pk if self.near_area else None),
            ('near_poi', self.near_poi.pk if self.near_poi else None),
            ('altitude', None if self.altitude is None else round(self.altitude, 2))
        ))
        if not grid.enabled:
            result.pop('grid_square')
        if include_type:
            result['type'] = 'custom'
            result.move_to_end('type', last=False)
        if simple_geometry:
            result['point'] = (self.level.pk, self.x, self.y)
            result['bounds'] = ((int(math.floor(self.x)), int(math.floor(self.y))),
                                (int(math.ceil(self.x)), int(math.ceil(self.y))))

        if geometry:
            result['geometry'] = self.serialized_geometry

        return result

    def details_display(self, **kwargs):
        result = {
            'id': self.pk,
            'display': [
                (_('Type'), _('Coordinates')),
                (_('ID'), self.pk),
                (_('Slug'), self.pk),
                (_('Level'), {
                    'id': self.level.pk,
                    'slug': self.level.get_slug(),
                    'title': self.level.title,
                    'can_search': self.level.can_search,
                }),
                (_('Space'), {
                    'id': self.space.pk,
                    'slug': self.space.get_slug(),
                    'title': self.space.title,
                    'can_search': self.space.can_search,
                } if self.space else None),
                (_('Areas'), tuple({
                    'id': area.pk,
                    'slug': area.get_slug(),
                    'title': area.title,
                    'can_search': area.can_search,
                } for area in self.areas)),
                (_('Grid Square'), self.grid_square or None),
                (_('Near Area'), {
                    'id': self.near_area.pk,
                    'slug': self.near_area.get_slug(),
                    'title': self.near_area.title,
                    'can_search': self.near_area.can_search,
                } if self.near_area else None),
                (_('Near POI'), {
                    'id': self.near_poi.pk,
                    'slug': self.near_poi.get_slug(),
                    'title': self.near_poi.title,
                    'can_search': self.near_poi.can_search,
                } if self.near_poi else None),
                (_('X Coordinate'), str(self.x)),
                (_('Y Coordinate'), str(self.y)),
                (_('Altitude'), None if self.altitude is None else str(round(self.altitude, 2))),
                (_('Title'), self.title),
                (_('Subtitle'), self.subtitle),
            ],
            'geometry': self.serialized_geometry,
        }
        if not grid.enabled:
            result['display'].pop(6)
        return result

    def get_geometry(self, detailed_geometry=True):
        return None

    @cached_property
    def description(self):
        from c3nav.routing.router import Router
        return Router.load().describe_custom_location(self)

    @cached_property
    def space(self):
        return self.description.space

    @cached_property
    def altitude(self):
        return self.description.altitude

    @cached_property
    def areas(self):
        return self.description.areas

    @cached_property
    def near_area(self):
        return self.description.near_area

    @cached_property
    def near_poi(self):
        return self.description.near_poi

    @cached_property
    def grid_square(self):
        return grid.get_square_for_point(self.x, self.y) or ''

    @cached_property
    def title_subtitle(self):
        grid_square = self.grid_square
        level_subtitle = self.level.title if not grid_square else ','.join((grid_square, str(self.level.title)))

        title = _('In %(level)s') % {'level': self.level.title}
        if not self.space:
            return title, level_subtitle

        subtitle = ()
        if self.near_poi:
            title = _('Near %(poi)s') % {'poi': self.near_poi.title}
            if self.areas:
                subtitle = (area.title for area in self.areas[:2])
            elif self.near_area:
                subtitle = (_('near %(area)s') % {'area': self.near_area.title}, )
        elif self.areas:
            title = _('In %(area)s') % {'area': self.areas[0].title}
            if self.areas:
                subtitle = (area.title for area in self.areas[1:2])
        elif self.near_area:
            title = _('Near %(area)s') % {'area': self.near_area.title}
        else:
            return _('In %(space)s') % {'space': self.space.title}, level_subtitle

        subtitle_segments = chain((grid_square, ), subtitle, (self.space.title, self.level.title))
        subtitle = ', '.join(str(title) for title in subtitle_segments if title)
        return title, subtitle

    @cached_property
    def title(self):
        return self.title_subtitle[0]

    @cached_property
    def subtitle(self):
        return self.title_subtitle[1]
