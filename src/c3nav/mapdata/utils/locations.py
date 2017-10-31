import operator
from functools import reduce
from typing import List, Mapping, Optional

from django.apps import apps
from django.core.cache import cache
from django.db.models import Prefetch, Q

from c3nav.mapdata.models import Level, Location, LocationGroup
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
    levels = {pk: obj for pk, obj in locations.items() if isinstance(obj, Level)}
    for obj in locations.values():
        if isinstance(obj, LevelGeometryMixin):
            obj.level_cache = levels.get(obj.level_id, None)

    # add spaces to areas and POIs
    spaces = {pk: obj for pk, obj in locations.items() if isinstance(obj, Space)}
    for obj in locations.values():
        if isinstance(obj, SpaceGeometryMixin):
            obj.space_cache = spaces.get(obj.space_id, None)

    # add targets to LocationRedirects
    levels = {pk: obj for pk, obj in locations.items() if isinstance(obj, Level)}
    for obj in locations.values():
        if isinstance(obj, LocationRedirect):
            obj.target_cache = locations.get(obj.target_id, None)

    # precache cached properties
    for obj in locations.values():
        # noinspection PyStatementEffect
        obj.subtitle, obj.order
        if isinstance(obj, GeometryMixin):
            # noinspection PyStatementEffect
            obj.centroid

    cache.set(cache_key, locations, 300)

    return locations


def visible_locations_for_request(request) -> Mapping[int, Location]:
    cache_key = 'mapdata:locations:real:%s' % AccessPermission.cache_key_for_request(request)
    locations = cache.get(cache_key, None)
    if locations is not None:
        return locations

    locations = {pk: location for pk, location in locations_for_request(request).items()
                 if not isinstance(location, LocationRedirect) and (location.can_search or location.can_describe)}

    cache.set(cache_key, locations, 300)

    return locations


def searchable_locations_for_request(request) -> List[Location]:
    cache_key = 'mapdata:locations:searchable:%s' % AccessPermission.cache_key_for_request(request)
    locations = cache.get(cache_key, None)
    if locations is not None:
        return locations

    locations = (location for location in locations_for_request(request).values() if isinstance(location, Location))
    locations = tuple(location for location in locations if location.can_search)

    locations = sorted(locations, key=operator.attrgetter('order'), reverse=True)

    cache.set(cache_key, locations, 300)

    return locations


def locations_by_slug_for_request(request) -> Mapping[str, LocationSlug]:
    cache_key = 'mapdata:locations:by_slug:%s' % AccessPermission.cache_key_for_request(request)
    locations = cache.get(cache_key, None)
    if locations is not None:
        return locations

    locations = {location.slug: location for location in locations_for_request(request).values() if location.slug}

    cache.set(cache_key, locations, 300)

    return locations


def get_location_by_slug_for_request(slug: str, request) -> Optional[LocationSlug]:
    cache_key = 'mapdata:location:by_slug:%s:%s' % (AccessPermission.cache_key_for_request(request), slug)
    locations = cache.get(cache_key, None)
    if locations is not None:
        return locations

    if ':' in slug:
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

    cache.set(cache_key, location, 300)

    return locations
