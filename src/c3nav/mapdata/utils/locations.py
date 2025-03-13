import math
import operator
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from itertools import chain
from typing import Mapping, Optional, ClassVar, NamedTuple, overload, Literal

from django.conf import settings
from django.db.models import Prefetch
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from pydantic import PositiveInt
from shapely import Point
from shapely.ops import unary_union

from c3nav.api.schema import GeometriesByLevelSchema
from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.grid import grid
from c3nav.mapdata.models import Level, Location, LocationGroup, MapUpdate
from c3nav.mapdata.models.geometry.level import Space, LevelGeometryMixin
from c3nav.mapdata.models.geometry.space import SpaceGeometryMixin
from c3nav.mapdata.models.locations import LocationSlug, Position, SpecificLocation
from c3nav.mapdata.permissions import active_map_permissions, LazyMapPermissionFilteredMapping, ManualMapPermissions
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


def merge_bounds(*bounds: BoundsByLevelSchema) -> BoundsByLevelSchema:
    collected_bounds = {}
    for one_bounds in bounds:
        for level_id, level_bounds in one_bounds.items():
            collected_bounds.setdefault(level_id, []).append(chain(*level_bounds))
    zipped_bounds = {level_id: tuple(zip(*level_bounds)) for level_id, level_bounds in collected_bounds.items()}
    return {level_id: ((min(zipped[0]), min(zipped[1])), (max(zipped[2]), max(zipped[3])))
            for level_id, zipped in zipped_bounds.items()}


def get_all_locations() -> LazyMapPermissionFilteredMapping[int, SpecificLocation | LocationGroup]:
    """
    Return all locations for this map permission context, by ID.
    This returns a dictionary, which is already sorted by order.
    The resulting data is automatically filtered by the active map permission.
    """
    # todo: obviously this should just be precalculated at this point
    cache_key = f'mapdata:locations:{MapUpdate.current_cache_key()}'
    locations: LazyMapPermissionFilteredMapping[int, SpecificLocation | LocationGroup]
    locations = proxied_cache.get(cache_key, None)
    if locations is not None:
        return locations

    with active_map_permissions.override(ManualMapPermissions.get_full_access()):
        locations = LazyMapPermissionFilteredMapping(_get_locations())

    proxied_cache.set(cache_key, locations, 1800)

    return locations


def _get_locations() -> dict[int, SpecificLocation | LocationGroup]:
    # todo this takes a long time because it's a lot of data, we might want to change that

    # todo: BAD BAD BAD! IDs can collide (for now, but not for much longer)
    locations = {location.pk: location for location in sorted((
        *SpecificLocation.objects.prefetch_related(
           Prefetch('groups', LocationGroup.objects.select_related(
               'category', 'label_settings'
           ).prefetch_related("slug_set")),
           # todo: starting to think that bounds and subtitles should be cached so we don't need… this
           Prefetch('levels', Level.objects.prefetch_related('buildings', 'altitudeareas')),
           Prefetch('spaces'),
           Prefetch('areas'),
           Prefetch('pois'),
           Prefetch('dynamiclocations'),
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

    levels = {level.pk: level for level in Level.objects.all()}
    spaces = {space.pk: space for space in Space.objects.select_related('level').prefetch_related(
        "locations__groups", "locations__slug_set"
    )}

    # trigger some cached properties, then empty prefetch_related cache
    for obj in chain(levels.values(), spaces.values()):
        for location in obj.sorted_locations:
            # noinspection PyStatementEffect
            location.slug
            # noinspection PyStatementEffect
            location.redirect_slugs
            # noinspection PyStatementEffect
            location.sorted_groups
            location._prefetched_objects_cache = {}

        obj._prefetched_objects_cache = {}

    # add levels to spaces: todo: hide locations etc bluh… what if a location has only on target and it's invisible?
    for pk, obj in locations.items():
        if not isinstance(obj, SpecificLocation):
            continue
        targets = tuple(obj.all_targets)
        for target in targets:
            if isinstance(target, LevelGeometryMixin):
                level = levels.get(target.level_id, None)
                if level is not None:
                    target.level = level
            elif isinstance(target, SpaceGeometryMixin):
                space = spaces.get(target.space_id, None)
                if space is not None:
                    target.space = space
        # todo: we want to hide locations that only have targets in an invisible level… probably

    # apply better space geometries TODO: do this again?
    #for pk, geometry in get_better_space_geometries().items():
    #    if pk in locations:
    #        locations[pk].geometry = geometry

    # trigger some cached properties, then empty prefetch_related cache
    for obj in locations.values():
        # noinspection PyStatementEffect
        obj.slug
        # noinspection PyStatementEffect
        obj.redirect_slugs

        if isinstance(obj, SpecificLocation):
            # noinspection PyStatementEffect
            obj.dynamic_targets
            # noinspection PyStatementEffect
            obj.sorted_groups

            for target in obj.static_targets:
                # noinspection PyStatementEffect
                target.bounds
                # noinspection PyStatementEffect
                target.points
                target._prefetched_objects_cache = {}

        obj._prefetched_objects_cache = {}

    return locations


def get_better_space_geometries():
    # change space geometries for better representative points
    cache_key = f'mapdata:better_space_geometries:{MapUpdate.current_cache_key()}'
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


def get_visible_locations() -> dict[int, Location]:
    """
    Return all visible locations for this map permission context (can_search or can_describe), by ID.
    This list has to be per context, because it includes the correct prefetch_related visibility filters etc,
    This returns a dictionary, which is already sorted by order.
    """
    # todo: cache this better, obviously
    return {
        pk: location
        for pk, location in get_all_locations().items()
        if location.can_search or location.can_describe
    }


def get_searchable_locations() -> dict[int, Location]:
    """
    Return all searchable locations for this map permission context, by ID.
    This list has to be per context, because it includes the correct prefetch_related visibility filters etc,
    This returns a dictionary, which is already sorted by order.
    """
    # todo: cache this better, obviously
    return {
        pk: location
        for pk, location in get_all_locations().items()
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


def levels_by_level_index_for_request() -> Mapping[str, Level]:
    """
    Get mapping of level index to level
    """
    cache_key = 'mapdata:levels:by_level_index:%s' % active_map_permissions.cache_key
    levels = proxied_cache.get(cache_key, None)
    if levels is not None:
        return levels

    levels = OrderedDict(
        (level.level_index, level)
        for level in Level.objects.filter(on_top_of_id__isnull=True).order_by('base_altitude')
    )

    proxied_cache.set(cache_key, levels, 1800)

    return levels


def get_custom_location_for_request(identifier: CustomLocationIdentifier) -> Optional["CustomLocation"]:
    """
    Get a custom location based on the given identifier
    """
    match = re.match(r'^c:(?P<level>[a-z0-9-_.]+):(?P<x>-?\d+(\.\d+)?):(?P<y>-?\d+(\.\d+)?)$', identifier)
    if match is None:
        return None
    level = levels_by_level_index_for_request().get(match.group('level'))
    if not isinstance(level, Level):
        return None
    return CustomLocation(
        level=level,
        x=float(match.group('x')),
        y=float(match.group('y')),
    )


@overload
def get_location(identifier: int) -> Optional[LocationProtocol]:
    pass


@overload
def get_location(identifier: int, *, redirect: Literal[True]) -> Optional[LocationProtocol | LocationRedirect]:
    pass


@overload
def get_location(identifier: str, *, redirect: Literal[False]) -> Optional[LocationProtocol]:
    pass


@overload
def get_location(identifier: str, *, redirect: Literal[True] = True) -> Optional[LocationProtocol | LocationRedirect]:
    pass


def get_location(identifier: int | str, *, redirect: bool = None) -> Optional[LocationProtocol | LocationRedirect]:
    """
    Get a location based on the given identifier for the given map permission context.

    if redirect is True (default if you pass a string as the identifier), you will get back a LocationRedirect if
    there is a preferable identifier (e.g. the location has a slug and you used its id or a redirect slug).

    Note that IDs can be passed either as strings or integers, but the latter changes the default redirect behavior.
    """
    if redirect is None:
        redirect = not isinstance(identifier, int)

    # Is this an integer? Then get the location by its ID.
    if isinstance(identifier, int) or identifier.isdigit():
        location = get_all_locations().get(int(identifier))

        # Return redirect if the location has a slug.
        return LocationRedirect(
            identifier=identifier,
            target=location,
        ) if (location.slug and redirect) else location

    # If this looks like a custom location identifier, get the custom location
    if identifier.startswith('c:'):
        return get_custom_location_for_request(identifier)

    # If this looks lik a position identifier, get the position
    if identifier.startswith('m:'):
        # return immediately, don't cache for obvious reasons
        return Position.objects.filter(secret=identifier[2:]).first()

    # Otherwise, this must be a slug, get the location target associated with this slug
    slug_target = _locations_by_slug().get(identifier, None)
    if slug_target is None:
        # No ID? Then this slug can't be found.
        return None

    # Get the location from the available locations for this request.
    location = get_all_locations().get(slug_target.target_id, None)

    # If this should be a redirect, return a redirect if we found the location, otherwise return the location (or None)
    return LocationRedirect(
        identifier=identifier,
        target=location,
    ) if (slug_target.redirect and location is not None and redirect) else location


@dataclass
class CustomLocation:
    """
    A custom location defined by coordinates.
    Implements :py:class:`c3nav.mapdata.schemas.locations.SingleLocationProtocol`.
    """
    locationtype: ClassVar = "customlocation"
    slug_as_id = False

    can_search = True
    can_describe = True
    access_restriction_id = None

    id: str = field(init=False)
    level: Level
    x: float | int
    y: float | int
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

    def details_display(self, **kwargs):
        result = {
            'id': self.pk,
            'display': [
                (_('Type'), _('Coordinates')),
                (_('ID'), self.id),
                (_('Slug'), self.id),
                (_('Level'), self.level.for_details_display()),
                (_('Space'), self._description.space.for_details_display() if self._description.space else None),
                (_('Areas'), tuple({
                    'id': area.pk,
                    'slug': area.effective_slug,
                    'title': area.title,
                    'can_search': area.can_search,
                } for area in self._description.areas)),
                (_('Grid Square'), self.grid_square or None),
                (_('Near Area'), {
                    'id': self._description.near_area.pk,
                    'slug': self._description.near_area.effective_slug,
                    'title': self._description.near_area.title,
                    'can_search': self._description.near_area.can_search,
                } if self._description.near_area else None),
                (_('Near POI'), {
                    'id': self._description.near_poi.pk,
                    'slug': self._description.near_poi.effective_slug,
                    'title': self._description.near_poi.title,
                    'can_search': self._description.near_poi.can_search,
                } if self._description.near_poi else None),
                (_('X Coordinate'), str(self.x)),
                (_('Y Coordinate'), str(self.y)),
                (_('Altitude'), None if self._description.altitude is None else str(round(self.altitude, 2))),
                (_('Title'), self.title),
                (_('Subtitle'), self.subtitle),
            ],
        }
        if not grid.enabled:
            result['display'].pop(6)
        return result

    @property
    def geometries_by_level(self) -> GeometriesByLevelSchema:
        return {}

    @property
    def geometries_or_points_by_level(self) -> GeometriesByLevelSchema:
        return {self.level.pk: [Point(self.x, self.y)]}

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
