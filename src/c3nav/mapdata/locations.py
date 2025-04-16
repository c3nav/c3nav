import math
import re
from dataclasses import dataclass, field
from itertools import chain
from typing import Optional, ClassVar, NamedTuple, overload, Literal, TypeAlias

from django.core.cache import cache
from django.db.models.query import Prefetch
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from pydantic import PositiveInt
from shapely import Point

from c3nav.api.schema import GeometriesByLevelSchema
from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.grid import grid
from c3nav.mapdata.models import Level, MapUpdate
from c3nav.mapdata.models.locations import LocationSlug, Position, DefinedLocation
from c3nav.mapdata.permissions import active_map_permissions, MapPermissionGuardedMapping
from c3nav.mapdata.schemas.locations import LocationProtocol, NearbySchema
from c3nav.mapdata.schemas.model_base import LocationPoint, BoundsByLevelSchema, LocationIdentifier, \
    CustomLocationIdentifier
from c3nav.mapdata.utils.cache.proxied import versioned_per_request_cache
from c3nav.mapdata.utils.cache.types import MapUpdateTuple

try:
    from asgiref.local import Local as LocalContext
except ImportError:
    from threading import local as LocalContext


@dataclass
class LocationRedirect:
    identifier: LocationIdentifier
    target: DefinedLocation


LazyDatabaseLocationById: TypeAlias = MapPermissionGuardedMapping[int, DefinedLocation]


class SlugTarget(NamedTuple):
    target_id: PositiveInt
    redirect: True


class LocationManager:
    _cache_key: MapUpdateTuple | None = None
    _all_locations: LazyDatabaseLocationById = MapPermissionGuardedMapping({})
    _visible_locations: LazyDatabaseLocationById = MapPermissionGuardedMapping({})
    _searchable_locations: LazyDatabaseLocationById = MapPermissionGuardedMapping({})
    _locations_by_slug: dict[NonEmptyStr, SlugTarget] = {}
    _levels_by_level_index: MapPermissionGuardedMapping[str, Level] = MapPermissionGuardedMapping({})

    @classmethod
    def levels_by_level_index(cls) -> MapPermissionGuardedMapping[str, Level]:
        """
        Get mapping of level index to level
        """
        cls._maybe_update()
        return cls._levels_by_level_index

    @classmethod
    def get_all(cls) -> LazyDatabaseLocationById:
        """
        Get all available locations under the current map permission context
        """
        cls._maybe_update()
        return cls._all_locations

    @classmethod
    def get_visible(cls) -> LazyDatabaseLocationById:
        """
        Get all visible (can_search or can_describe) locations under the current map permission context
        """
        cls._maybe_update()
        return cls._visible_locations

    @classmethod
    def get_searchable(cls) -> LazyDatabaseLocationById:
        """
        Get all searchable (can_search or can_describe) locations under the current map permission context
        """
        cls._maybe_update()
        return cls._searchable_locations

    @classmethod
    @overload
    def get(cls, identifier: int) -> Optional[LocationProtocol]:
        pass

    @classmethod
    @overload
    def get(cls, identifier: int, *, redirect: Literal[True]) -> Optional[LocationProtocol | LocationRedirect]:
        pass

    @classmethod
    @overload
    def get(cls, identifier: str, *, redirect: Literal[False]) -> Optional[LocationProtocol]:
        pass

    @classmethod
    @overload
    def get(cls, identifier: str, *, redirect: Literal[True] = True) -> Optional[LocationProtocol | LocationRedirect]:
        pass

    @classmethod
    def get(cls, identifier: int | str, *, redirect: bool = None) -> Optional[LocationProtocol | LocationRedirect]:
        """
        Get a location based on the given identifier for the given map permission context.

        if redirect is True (default if you pass a string as the identifier), you will get back a LocationRedirect if
        there is a preferable identifier (e.g. the location has a slug and you used its id or a redirect slug).

        Note that IDs can be passed either as strings or integers, but the latter changes the default redirect behavior.
        """
        cls._maybe_update()

        if redirect is None:
            redirect = not isinstance(identifier, int)

        # Is this an integer? Then get the location by its ID.
        if isinstance(identifier, int) or identifier.isdigit():
            location = cls._all_locations.get(int(identifier))

            # Return redirect if the location has a slug.
            return LocationRedirect(
                identifier=identifier,
                target=location,
            ) if (location.slug and redirect) else location

        # If this looks like a custom location identifier, get the custom location
        if identifier.startswith('c:'):
            return cls._get_custom_location(identifier)

        # If this looks lik a position identifier, get the position
        if identifier.startswith('m:'):
            # return immediately, don't cache for obvious reasons
            return Position.objects.filter(secret=identifier[2:]).first()

        # Otherwise, this must be a slug, get the location target associated with this slug
        slug_target = cls._locations_by_slug.get(identifier, None)
        if slug_target is None:
            # No ID? Then this slug can't be found.
            return None

        # Get the location from the available locations for this request.
        location = cls._all_locations.get(slug_target.target_id, None)

        # If this should be a redirect, return a redirect if we found the location, otherwise return the location (or None)
        return LocationRedirect(
            identifier=identifier,
            target=location,
        ) if (slug_target.redirect and location is not None and redirect) else location

    @classmethod
    def _get_custom_location(cls, identifier: CustomLocationIdentifier) -> Optional["CustomLocation"]:
        match = re.match(r'^c:(?P<level>[a-z0-9-_.]+):(?P<x>-?\d+(\.\d+)?):(?P<y>-?\d+(\.\d+)?)$', identifier)
        if match is None:
            return None
        level = cls._levels_by_level_index.get(match.group('level'))
        if not isinstance(level, Level):
            return None
        return CustomLocation(
            level=level,
            x=float(match.group('x')),
            y=float(match.group('y')),
        )

    @classmethod
    def _maybe_update(cls):
        update = MapUpdate.last_update("recalculate_definedlocation_final")
        update_id = None if update is None else update.update_id
        if update_id != cls._cache_key:
            cls.update(update_id)

    @classmethod
    def update(cls, update_id: int | None):
        # todo: altitude of points could change later!!
        cls._cache_key = update_id
        with active_map_permissions.disable_access_checks():
            cache_key = f'mapdata:all_locations:{update_id}'
            all_locations: dict[int, DefinedLocation] | None
            all_locations = cache.get(cache_key, None)
            if all_locations is None:
                all_locations = cls.generate_locations_by_id()
                cache.set(cache_key, all_locations, 1800)
            cls._all_locations = MapPermissionGuardedMapping(all_locations)
            cls._visible_locations = MapPermissionGuardedMapping({
                pk: location for pk, location in all_locations.items()
                if location.can_search or location.can_describe
            })
            cls._searchable_locations = MapPermissionGuardedMapping({
                pk: location for pk, location in all_locations.items()
                if location.can_describe
            })
            cls._locations_by_slug = {
                location_slug.slug: SlugTarget(target_id=location_slug.target_id, redirect=location_slug.redirect)
                for location_slug in LocationSlug.objects.all()
            }
            cls._levels_by_level_index = MapPermissionGuardedMapping({
                level.level_index: level
                for level in Level.objects.filter(on_top_of_id__isnull=True).order_by('base_altitude')
            })

    @classmethod
    def generate_locations_by_id(cls) -> dict[int, DefinedLocation]:
        locations = {
            location.pk: location for location in DefinedLocation.objects.select_related(
                "effective_label_settings",
                "load_group_display",
            ).prefetch_related(
                "slug_set",
                "calculated_descendants",
                Prefetch("calculated_ancestors",
                         DefinedLocation.objects.order_by("effective_traversal_order")),
            ).order_by("effective_depth_first_order")
        }

        # trigger some cached properties, then empty prefetch_related cache
        for obj in locations.values():
            # noinspection PyStatementEffect
            obj.slug, obj.redirect_slugs, obj.sublocations, obj.display_superlocations
            # clear prefetch cache
            obj._prefetched_objects_cache = {}

        return locations


@dataclass
class CustomLocation:
    """
    A custom location defined by coordinates.
    Implements :py:class:`c3nav.mapdata.schemas.locations.SingleLocationProtocol`.
    """
    locationtype: ClassVar = "custom"
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
        # todo: this still needs adjustment for groups-less location hierarchy
        result = {
            'id': self.id,
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
                (_('Altitude'), (None if self._description.altitude is None
                                 else str(round(self._description.altitude, 2)))),
                (_('Title'), self.title),
                (_('Subtitle'), self.subtitle),
            ],
        }
        if not grid.enabled:
            result['display'].pop(6)
        return result

    @property
    def geometries_by_level(self) -> GeometriesByLevelSchema:
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


def get_random_location_parents() -> frozenset[int]:
    cache_key = "mapdata:random_locations"
    from c3nav.mapdata.models import MapUpdate
    last_update = MapUpdate.last_update()
    result = versioned_per_request_cache.get(last_update, cache_key, None)
    if result is not None:
        return result
    result = frozenset(DefinedLocation.objects.filter(include_in_random_location=True).values_list("pk", flat=True))
    versioned_per_request_cache.set(last_update, cache_key, result, 3600)
    return result