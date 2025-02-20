import math
import operator
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from itertools import chain
from typing import Any, List, Mapping, Optional, ClassVar, NamedTuple, Sequence

from django.conf import settings
from django.db.models import Prefetch
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from pydantic import PositiveInt
from shapely.ops import unary_union

from c3nav.api.schema import GeometryByLevelSchema
from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.grid import grid
from c3nav.mapdata.models import Level, Location, LocationGroup, MapUpdate
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.models.geometry.base import GeometryMixin
from c3nav.mapdata.models.geometry.level import Space, LevelGeometryMixin
from c3nav.mapdata.models.geometry.space import POI, Area, SpaceGeometryMixin
from c3nav.mapdata.models.locations import LocationSlug, Position, SpecificLocation, DynamicLocation
from c3nav.mapdata.schemas.locations import LocationProtocol, NearbySchema
from c3nav.mapdata.schemas.model_base import LocationPoint, BoundsByLevelSchema, LocationIdentifier, \
    CustomLocationIdentifier
from c3nav.mapdata.utils.cache.local import LocalCacheProxy
from c3nav.mapdata.utils.geometry import unwrap_geom

proxied_cache = LocalCacheProxy(maxsize=settings.CACHE_SIZE_LOCATIONS)


@dataclass
class LocationRedirect:
    identifier: LocationIdentifier
    target: Location


def locations_for_request(request) -> dict[int, Location]:
    """
    Return all locations for this request, by ID.
    This list has to be per request, because it includes the correct prefetch_related visibility filters etc,
    This returns a dictionary, which is already sorted by order.
    """
    # todo this takes a long time because it's a lot of data, we might want to change that
    cache_key = 'mapdata:locations:%s' % AccessPermission.cache_key_for_request(request)
    locations: dict[int, Location]
    locations = proxied_cache.get(cache_key, None)
    if locations is not None:
        return locations

    # todo: BAD BAD BAD! IDs can collide (for now, but not for much longer)
    locations = {location.pk: location for location in sorted((
        *SpecificLocation.qs_for_request(request).prefetch_related(
           Prefetch('groups', LocationGroup.qs_for_request(request).select_related(
               'category', 'label_settings'
           ).prefetch_related("slug_set")),
           # todo: starting to think that bounds and subtitles should be cached so we don't need… this
           Prefetch('levels', Level.qs_for_request(request).prefetch_related('buildings', 'altitudeareas')),
           Prefetch('spaces', Space.qs_for_request(request)),
           Prefetch('areas', Area.qs_for_request(request)),
           Prefetch('pois', POI.qs_for_request(request)),
           Prefetch('dynamiclocations', DynamicLocation.qs_for_request(request)),
        ).select_related('label_settings').prefetch_related("slug_set"),
        *LocationGroup.objects.select_related(
            'category', 'label_settings'
        ).prefetch_related("slug_set"),
    ), key=operator.attrgetter('order'), reverse=True)}

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
    spaces = {space.pk: space
              for space in Space.qs_for_request(request).select_related('level').prefetch_related("locations__groups")}

    # add levels to spaces: todo: fix this! hide locations etc bluh bluh
    remove_pks = set()
    for pk, obj in locations.items():
        if not isinstance(obj, SpecificLocation):
            continue
        targets = tuple(obj.get_targets())
        for target in targets:
            if isinstance(target, LevelGeometryMixin):
                level = levels.get(target.level_id, None)
                if level is not None:
                    target.level = level
            elif isinstance(target, SpaceGeometryMixin):
                space = spaces.get(target.space_id, None)
                if space is not None:
                    target.space = space
        # todo: we don't want to remove things for groups of course, so once we merge these in… keep that in mind
        if not targets:
            remove_pks.add(pk)

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


def visible_locations_for_request(request) -> dict[int, Location]:
    """
    Return all visible locations for this request (can_search or can_describe), by ID.
    This list has to be per request, because it includes the correct prefetch_related visibility filters etc,
    This returns a dictionary, which is already sorted by order.
    """
    return {
        pk: location
        for pk, location in locations_for_request(request).items()
        if location.can_search or location.can_describe
    }


def searchable_locations_for_request(request) -> dict[int, Location]:
    """
    Return all searchable locations for this request, by ID.
    This list has to be per request, because it includes the correct prefetch_related visibility filters etc,
    This returns a dictionary, which is already sorted by order.
    """
    return {
        pk: location
        for pk, location in locations_for_request(request).items()
        if location.can_search
    }


class SlugTarget(NamedTuple):
    target_id: PositiveInt
    redirect: True


def _locations_by_slug() -> Mapping[NonEmptyStr, SlugTarget]:
    """
    Get a mapping of slugs to slug targets.
    You need to check afterwards if the user is allowed to see it.
    """
    cache_key = 'mapdata:locations:by_slug'
    locations: Mapping[NonEmptyStr, PositiveInt]
    locations = proxied_cache.get(cache_key, None)
    if locations is not None:
        return locations

    locations = {
        location_slug.slug: SlugTarget(target_id=location_slug.target_id, redirect=location_slug.redirect)
         for location_slug in LocationSlug.objects.all()
    }
    proxied_cache.set(cache_key, locations, 1800)
    return locations


def levels_by_level_index_for_request(request) -> Mapping[str, Level]:
    """
    Get mapping of level index to level for requestz
    """
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


def get_custom_location_for_request(identifier: CustomLocationIdentifier, request) -> Optional["CustomLocation"]:
    """
    Get a custom location based on the given identifier
    """
    match = re.match(r'^c:(?P<level>[a-z0-9-_.]+):(?P<x>-?\d+(\.\d+)?):(?P<y>-?\d+(\.\d+)?)$', identifier)
    if match is None:
        return None
    level = levels_by_level_index_for_request(request).get(match.group('level'))
    if not isinstance(level, Level):
        return None
    return CustomLocation(level, float(match.group('x')), float(match.group('y')),
                          AccessPermission.get_for_request(request))


def get_location_for_request(identifier: int | str, request) -> Optional[LocationProtocol | LocationRedirect]:
    """
    Get a location based on the given identifier for the given request
    """

    # Is this an integer? Then get the location by it's ID.
    if isinstance(identifier, int) or identifier.isdigit():
        location = locations_for_request(request).get(int(identifier))

        # Return redirect if the location has a slug.
        return LocationRedirect(
            identifier=identifier,
            target=location,
        ) if location.slug else location

    # If this looks like a custom location identifier, get the custom location
    if identifier.startswith('c:'):
        return get_custom_location_for_request(identifier, request)

    # If this looks lik a position identifier, get the position
    if identifier.startswith('m:'):
        # return immediately, don't cache for obvious reasons
        return Position.objects.filter(secret=identifier[2:]).first()

    # Otherwise, this must be a slug, get the location target associated with this slug
    target = _locations_by_slug().get(identifier, None)
    if target is None:
        # No ID? Then this slug can't be found.
        return None

    # Get the location from the available locations for this request.
    location = locations_for_request(request).get(target.target_id, None)

    # If this should be a redirect, return a redirect if we found the location, otherwise return the location (or None)
    return LocationRedirect(
        identifier=identifier,
        target=location,
    ) if (target.redirect and location is not None) else location


@dataclass
class CustomLocation:
    locationtype: ClassVar = "customlocation"
    slug_as_id = False

    can_search = True
    can_describe = True
    access_restriction_id = None

    id: str = field(init=False)
    level: Level
    x: float | int
    y: float | int
    permissions: Any = ()  # todo: correct this
    icon: str = "pin_drop"

    def __post_init__(self):
        x = round(self.x, 2)
        y = round(self.y, 2)
        self.id = 'c:%s:%s:%s' % (self.level.level_index, x, y)

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
    def point(self) -> LocationPoint:
        return (self.level.pk, self.x, self.y)

    @property
    def points(self) -> list[LocationPoint]:
        return [self.point]

    @property
    def bounds(self) -> BoundsByLevelSchema:
        return {self.level.pk: ((int(math.floor(self.x)), int(math.floor(self.y))),
                                (int(math.ceil(self.x)), int(math.ceil(self.y))))}

    def details_display(self, request, **kwargs):
        result = {
            'id': self.pk,
            'display': [
                (_('Type'), _('Coordinates')),
                (_('ID'), self.id),
                (_('Slug'), self.id),
                (_('Level'), self.level.for_details_display()),
                (_('Space'), self.space.for_details_display() if self.space else None),
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
        }
        if not grid.enabled:
            result['display'].pop(6)
        return result

    def get_geometry(self, request) -> GeometryByLevelSchema:
        return {}

    @cached_property
    def _description(self):
        from c3nav.routing.router import Router
        return Router.load().describe_custom_location(self)

    @cached_property
    def nearby(self) -> NearbySchema:
        return NearbySchema(
            level=self.level.pk,
            space=self._description.space.pk,
            areas=[pk for pk in self._description.areas],
            near_area=self._description.near_area.pk if self._description.near_area else None,
            near_poi=self._description.near_poi.pk if self._description.near_poi else None,
            near_locations=[pk for pk in self._description.nearby],
            altitude=self._description.altitude,
        )

    @cached_property
    def grid_square(self):
        return grid.get_square_for_point(self.x, self.y)

    @cached_property
    def title_subtitle(self):
        grid_square = self.grid_square
        level_subtitle = self.level.title if not grid_square else ', '.join((grid_square, str(self.level.title)))

        title = _('In %(level)s') % {'level': self.level.title}
        if not self._description.space:
            return title, level_subtitle

        subtitle = ()
        if self._description.near_poi:
            title = _('Near %(poi)s') % {'poi': self._description.near_poi.title}
            if self._description.areas:
                subtitle = (area.title for area in self._description.areas[:2])
            elif self._description.near_area:
                subtitle = (_('near %(area)s') % {'area': self._description.near_area.title}, )
        elif self._description.areas:
            title = _('In %(area)s') % {'area': self._description.areas[0].title}
            if self._description.areas:
                subtitle = (area.title for area in self._description.areas[1:2])
        elif self._description.near_area:
            title = _('Near %(area)s') % {'area': self._description.near_area.title}
        else:
            return _('In %(space)s') % {'space': self._description.space.title}, level_subtitle

        subtitle_segments = chain((grid_square, ), subtitle, (self._description.space.title, self.level.title))
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
        return self.id

    @cached_property
    def slug(self):
        return self.id
