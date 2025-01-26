import math
import operator
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from itertools import chain
from typing import Any, List, Mapping, Optional, Union, ClassVar

from django.conf import settings
from django.db.models import Prefetch
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from shapely.ops import unary_union

from c3nav.mapdata.grid import grid
from c3nav.mapdata.models import Level, Location, LocationGroup, MapUpdate
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.models.geometry.base import GeometryMixin
from c3nav.mapdata.models.geometry.level import LevelGeometryMixin, Space
from c3nav.mapdata.models.geometry.space import SpaceGeometryMixin
from c3nav.mapdata.models.locations import LocationSlug, Position, SpecificLocation
from c3nav.mapdata.utils.cache.local import LocalCacheProxy
from c3nav.mapdata.utils.geometry import unwrap_geom

proxied_cache = LocalCacheProxy(maxsize=settings.CACHE_SIZE_LOCATIONS)


@dataclass
class LocationRedirect:
    slug: str
    target: Location


def locations_for_request(request) -> Mapping[int, LocationSlug | Location]:
    # todo this takes a long time because it's a lot of data, we might want to change that
    cache_key = 'mapdata:locations:%s' % AccessPermission.cache_key_for_request(request)
    locations = proxied_cache.get(cache_key, None)
    if locations is not None:
        return locations

    # todo: BAD BAD BAD! IDs can collide (for now, but not for much longer)
    locations = {
        **{redirect_slug.pk: LocationRedirect(slug=redirect_slug.slug, target=redirect_slug.get_target())
           for redirect_slug in LocationSlug.objects.filter(redirect=True).order_by('id')},
        **{location.pk: location for location in SpecificLocation.objects.prefetch_related(
            Prefetch('groups', LocationGroup.qs_for_request(request).select_related('category',
                                                                                    'label_settings'))
        ).select_related('label_settings')},
        **{group.pk: group for group in LocationGroup.objects.select_related('category', 'label_settings')},
    }

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

    levels = {level.pk: level for level in Level.qs_for_request(request)}
    spaces = {space.pk: space for space in Space.qs_for_request(request).select_related('level')}

    # add levels to spaces: todo: fix this! hide locations etc bluh bluh
    remove_pks = set()
    for pk, obj in locations.items():
        if not isinstance(obj, SpecificLocation):
            continue
        target = obj.get_target()
        if isinstance(target, LevelGeometryMixin):
            level = levels.get(target.level_id, None)
            if level is None:
                remove_pks.add(pk)
                continue
            target._level_cache = level
        elif isinstance(target, SpaceGeometryMixin):
            space = spaces.get(target.space_id, None)
            if space is None:
                remove_pks.add(pk)
                continue
            target._space_cache = space

    # hide locations in hidden spaces or levels
    for pk in remove_pks:
        locations.pop(pk)

    # add targets to LocationRedirects
    remove_pks = set()
    for pk, obj in locations.items():
        if not isinstance(obj, LocationRedirect):
            continue
        target = locations.get(obj.target.pk, None)
        if target is None:
            remove_pks.add(pk)
            continue
        obj.target = target

    # hide redirects to hidden locations
    for pk in remove_pks:
        locations.pop(pk)

    # apply better space geometries TODO: do this again?
    #for pk, geometry in get_better_space_geometries().items():
    #    if pk in locations:
    #        locations[pk].geometry = geometry

    # precache cached properties
    for obj in locations.values():
        if isinstance(obj, LocationRedirect):
            continue
        # noinspection PyStatementEffect
        obj.subtitle, obj.order
        if isinstance(obj, GeometryMixin):  # TODO: do this again
            # noinspection PyStatementEffect
            obj.point

    proxied_cache.set(cache_key, locations, 1800)

    return locations


def get_better_space_geometries():
    # change space geometries for better representative points
    cache_key = 'mapdata:better_space_geometries:%s' % MapUpdate.current_cache_key()
    result = proxied_cache.get(cache_key, None)
    if result is not None:
        return result

    result = {}
    for space in Space.objects.prefetch_related('columns', 'holes'):
        geometry = space.geometry.difference(
            unary_union(tuple(unwrap_geom(obj.geometry) for obj in chain(space.columns.all(), space.holes.all())))
        )
        if not geometry.is_empty:
            result[space.pk] = geometry

    proxied_cache.set(cache_key, result, 1800)

    return result


def visible_locations_for_request(request) -> Mapping[int, Location]:
    cache_key = 'mapdata:locations:real:%s' % AccessPermission.cache_key_for_request(request)
    locations = proxied_cache.get(cache_key, None)
    if locations is not None:
        return locations

    locations = {pk: location for pk, location in locations_for_request(request).items()
                 if not isinstance(location, LocationRedirect) and (location.can_search or location.can_describe)}

    proxied_cache.set(cache_key, locations, 1800)

    return locations


def searchable_locations_for_request(request) -> List[Location]:
    cache_key = 'mapdata:locations:searchable:%s' % AccessPermission.cache_key_for_request(request)
    locations = proxied_cache.get(cache_key, None)
    if locations is not None:
        return locations

    locations = (location for location in locations_for_request(request).values() if isinstance(location, Location))
    locations = tuple(location for location in locations if location.can_search)

    locations = sorted(locations, key=operator.attrgetter('order'), reverse=True)

    proxied_cache.set(cache_key, locations, 1800)

    return locations


def locations_by_slug_for_request(request) -> Mapping[str, LocationSlug | Location]:
    cache_key = 'mapdata:locations:by_slug:%s' % AccessPermission.cache_key_for_request(request)
    locations = proxied_cache.get(cache_key, None)
    if locations is not None:
        return locations

    locations = {location.slug: location for location in locations_for_request(request).values() if location.slug}

    proxied_cache.set(cache_key, locations, 1800)

    return locations


def levels_by_level_index_for_request(request) -> Mapping[str, Level]:
    cache_key = 'mapdata:levels:by_level_index:%s' % AccessPermission.cache_key_for_request(request)
    levels = proxied_cache.get(cache_key, None)
    if levels is not None:
        return levels

    levels = OrderedDict(
        (level.level_index, level)
        for level in Level.qs_for_request(request).filter(on_top_of_id__isnull=True).order_by('base_altitude')
    )

    proxied_cache.set(cache_key, levels, 1800)

    return levels


def get_location_by_id_for_request(pk, request):
    if isinstance(pk, str):
        if pk.isdigit():
            pk = int(pk)
        elif pk.startswith('m:'):
            try:
                # return immediately, don't cache for obvious reasons
                return Position.objects.get(secret=pk[2:])
            except Position.DoesNotExist:
                return None
        else:
            return get_custom_location_for_request(pk, request)
    return locations_for_request(request).get(pk)


def get_location_by_slug_for_request(slug: str, request) -> Optional[Union[LocationSlug, Position]]:
    cache_key = 'mapdata:location:by_slug:%s:%s' % (AccessPermission.cache_key_for_request(request), slug)
    location = proxied_cache.get(cache_key, None)
    if location is not None:
        return location

    if slug.startswith('c:'):
        location = get_custom_location_for_request(slug, request)
        if location is None:
            return None
    elif slug.startswith('m:'):
        try:
            # return immediately, don't cache for obvious reasons
            return Position.objects.get(secret=slug[2:])
        except Position.DoesNotExist:
            return None
    elif ':' in slug or slug.isdigit():
        if ':' in slug:
            code, pk = slug.split(':', 1)
            model_name = LocationSlug.LOCATION_TYPE_BY_CODE.get(code, 'SpecificLocation')  # legacy fallback todo remove
            if model_name is None or not pk.isdigit():
                return None
        else:
            model_name = None
            pk = slug

        location = locations_for_request(request).get(int(pk), None)
        if location is None or (model_name is not None and location._meta.model_name != model_name.lower()):
            return None

        if location.slug is not None:
            location = LocationRedirect(slug=slug, target=location)
    else:
        location = locations_by_slug_for_request(request).get(slug, None)

    proxied_cache.set(cache_key, location, 1800)

    return location


def get_custom_location_for_request(slug: str, request):
    match = re.match(r'^c:(?P<level>[a-z0-9-_.]+):(?P<x>-?\d+(\.\d+)?):(?P<y>-?\d+(\.\d+)?)$', slug)
    if match is None:
        return None
    level = levels_by_level_index_for_request(request).get(match.group('level'))
    if not isinstance(level, Level):
        return None
    return CustomLocation(level, float(match.group('x')), float(match.group('y')),
                          AccessPermission.get_for_request(request))


@dataclass
class CustomLocation:
    locationtype: ClassVar = "customlocation"

    can_search = True
    can_describe = True
    access_restriction_id = None

    pk: str = field(init=False)
    level: Level
    x: float | int
    y: float | int
    permissions: Any = ()  # todo: correct this
    icon: str = "pin_drop"

    def __post_init__(self):
        x = round(self.x, 2)
        y = round(self.y, 2)
        self.pk = 'c:%s:%s:%s' % (self.level.level_index, x, y)

    @property
    def rounded_pk(self):
        return 'c:%s:%s:%s' % (self.level.level_index, self.x//5*5, self.y//5*5)

    @property
    def serialized_geometry(self):
        return {
            'type': 'Point',
            'coordinates': (self.x, self.y)
        }

    @property
    def point(self):
        return (self.level.pk, self.x, self.y)

    @property
    def bounds(self):
        return ((int(math.floor(self.x)), int(math.floor(self.y))),
                (int(math.ceil(self.x)), int(math.ceil(self.y))))

    def details_display(self, **kwargs):
        result = {
            'id': self.pk,
            'display': [
                (_('Type'), _('Coordinates')),
                (_('ID'), self.pk),
                (_('Slug'), self.pk),
                (_('Level'), {
                    'id': self.level.pk,
                    'slug': self.level.effective_slug,
                    'title': self.level.title,
                    'can_search': self.level.can_search,
                }),
                (_('Space'), {
                    'id': self.space.pk,
                    'slug': self.space.effective_slug,
                    'title': self.space.title,
                    'can_search': self.space.can_search,
                } if self.space else None),
                (_('Areas'), tuple({
                    'id': area.pk,
                    'slug': area.effective_slug,
                    'title': area.title,
                    'can_search': area.can_search,
                } for area in self.areas)),
                (_('Grid Square'), self.grid_square or None),
                (_('Near Area'), {
                    'id': self.near_area.pk,
                    'slug': self.near_area.effective_slug,
                    'title': self.near_area.title,
                    'can_search': self.near_area.can_search,
                } if self.near_area else None),
                (_('Near POI'), {
                    'id': self.near_poi.pk,
                    'slug': self.near_poi.effective_slug,
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
    def nearby(self):
        return self.description.nearby

    @cached_property
    def grid_square(self):
        return grid.get_square_for_point(self.x, self.y)

    @cached_property
    def title_subtitle(self):
        grid_square = self.grid_square
        level_subtitle = self.level.title if not grid_square else ', '.join((grid_square, str(self.level.title)))

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

    @property
    def effective_icon(self):
        return self.icon

    @property
    def effective_slug(self):
        return self.pk

    @cached_property
    def slug(self):
        return self.pk
