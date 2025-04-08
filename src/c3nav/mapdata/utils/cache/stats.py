from operator import itemgetter

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from kombu.utils import cached_property

from c3nav.control.models import UserPermissions
from c3nav.mapdata.grid import grid
from c3nav.mapdata.models import Level, LocationSlug, Space
from c3nav.mapdata.models.geometry.space import POI, Area, BeaconMeasurement
from c3nav.mapdata.locations import CustomLocation, LocationManager


def increment_cache_key(cache_key):
    try:
        cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 1, None)


def stats_snapshot(reset=True):
    last_now = cache.get('apistats_last_reset', '', None)
    now = timezone.now()
    results = {}
    for key in cache.keys('apistats__*'):
        results[key] = cache.get(key)
        if reset:
            cache.delete(key)
    if reset:
        cache.set('apistats_last_reset', now, None)
    results = dict(sorted(results.items()))
    return {
        'start_date': str(last_now),
        'end_date': str(now),
        'data': results
    }


def _filter_stats(tag, stats, startswith=False):
    if startswith:
        return (([name[0][len(tag):]]+name[1:], value) for name, value in stats if name[0].startswith(tag))
    return ((name[1:], value) for name, value in stats if name[0] == tag)


class FakeRequest():
    @cached_property
    def user(self):
        return get_user_model().objects.filter(is_superuser=True).first()

    @cached_property
    def user_permissions(self):
        return UserPermissions.get_for_user(self.user)


def convert_stats(stats):
    stats = [(name.split('__')[1:], value) for name, value in stats['data'].items()]
    result = {
        'locate': convert_locate(_filter_stats('locate', stats)),
        'location_retrieve': convert_location(_filter_stats('location_retrieve', stats)),
        'location_geometry': convert_location(_filter_stats('location_geometry', stats)),
        'route_origin': convert_location(
            (['pk'] + name, value) for name, value in _filter_stats('route_origin_', stats, startswith=True)
        ),
        'route_destination': convert_location(
            (['pk'] + name, value) for name, value in _filter_stats('route_destination_', stats, startswith=True)
        ),
    }
    return result


def _sort_count(map, key):
    map[key] = dict(sorted(map[key].items(), key=itemgetter(1), reverse=True))


def convert_locate(data):
    result = {
        'total': 0,
        'by_measurement_id': {},
        'by_grid_square': {},
        'by_space': {},
        'by_level': {},
    }
    measurement_lookup = {}
    for measurement in BeaconMeasurement.objects.all().select_related('space', 'space__level'):
        pos = CustomLocation(
            level=measurement.space.level,
            x=measurement.geometry.x,
            y=measurement.geometry.y
        )
        space_slug = measurement.space.effective_slug
        level_label = measurement.space.level.level_index
        grid_square = pos.grid_square if grid.enabled else None
        measurement_lookup[pos.pk] = (measurement.pk, grid_square, space_slug, level_label)
        result['by_measurement_id'][measurement.pk] = 0
        if grid_square:
            result['by_grid_square'][grid_square] = 0
        result['by_space'][space_slug] = 0
        result['by_level'][level_label] = 0

    for name, value in data:
        result['total'] += value
        measurement = measurement_lookup.get(name[0], None)
        if measurement:
            result['by_measurement_id'][measurement[0]] += value
            if measurement[1]:
                result['by_grid_square'][measurement[1]] += value
            result['by_space'][measurement[2]] += value
            result['by_level'][measurement[3]] += value

    _sort_count(result, 'by_measurement_id')
    _sort_count(result, 'by_space')
    _sort_count(result, 'by_level')
    return result


def convert_location(data):
    # todo: this still needs to be reimplemented with groups and all
    result = {
        'total': 0,
        'invalid': 0,
        'locations': {
            'total': 0,
            'by_type': {},
            'by_space': {},
            'by_level': {},
            'by_group': {},
        },
        'coordinates': {
            'total': 0,
            'by_level': {},
            'by_space': {},
            'by_area': {},
            'by_poi': {},
        }
    }

    # fill up lists with zeros
    location_slugs = {}
    level_indices = {}
    for location in LocationSlug.objects.all():
        location = location.get_child()
        if isinstance(location, LocationRedirect):
            continue
        result['locations']['by_type'].setdefault(location.__class__.__name__.lower(), {})[location.effective_slug] = 0
        location_slugs[location.pk] = location.effective_slug
        if isinstance(location, Level):
            result['locations']['by_level'][location.level_index] = 0
            result['coordinates']['by_level'][location.level_index] = 0
            level_indices[location.pk] = location.short_label
        if isinstance(location, Space):
            result['locations']['by_space'][location.effective_slug] = 0
            result['coordinates']['by_space'][location.effective_slug] = 0
        if isinstance(location, Area):
            if getattr(location, 'can_search', False) or getattr(location, 'can_describe', False):
                result['coordinates']['by_area'][location.effective_slug] = 0
        if isinstance(location, POI):
            if getattr(location, 'can_search', False) or getattr(location, 'can_describe', False):
                result['coordinates']['by_poi'][location.effective_slug] = 0
        if isinstance(location, LocationGroup):
            result['locations']['by_group'][location.effective_slug] = 0

    for name, value in data:
        if name[0] != 'pk' or name[0] == 'c:anywhere':
            continue
        location = LocationManager.get(name[1])
        result['total'] += value
        if location is None:
            result['invalid'] += value
            continue
        if isinstance(location, CustomLocation):
            location.x += 1.5
            location.y += 1.5
            result['coordinates']['total'] += value
            result['coordinates']['by_level'][location_slugs[location.level.pk]] += value
            if location.space is None:
                continue
            result['coordinates']['by_space'][location_slugs[location.space.pk]] += value
            for area in location.areas:
                result['coordinates']['by_area'][location_slugs[area.pk]] += value
            if location.near_area:
                result['coordinates']['by_area'][location_slugs[location.near_area.pk]] += value
            if location.near_poi:
                result['coordinates']['by_poi'][location_slugs[location.near_poi.pk]] += value
        else:
            result['locations']['total'] += value
            location = getattr(location, 'target', location)
            result['locations']['by_type'].setdefault(location.__class__.__name__.lower(),
                                                      {})[location.effective_slug] += value
            if hasattr(location, 'space_id'):
                result['locations']['by_space'][location_slugs[location.space_id]] += value
            if hasattr(location, 'level_id'):
                result['locations']['by_level'][level_indices[location.level_id]] += value
            if hasattr(location, 'groups'):
                for group in location.groups.all():
                    result['locations']['by_group'][location_slugs[group.pk]] += value

    _sort_count(result['locations']['by_type'], 'level')
    _sort_count(result['locations']['by_type'], 'space')
    _sort_count(result['locations']['by_type'], 'area')
    _sort_count(result['locations']['by_type'], 'poi')
    _sort_count(result['locations']['by_type'], 'locationgroup')
    _sort_count(result['locations'], 'by_space')
    _sort_count(result['locations'], 'by_level')
    _sort_count(result['locations'], 'by_group')
    _sort_count(result['coordinates'], 'by_level')
    _sort_count(result['coordinates'], 'by_space')
    _sort_count(result['coordinates'], 'by_area')
    _sort_count(result['coordinates'], 'by_poi')
    return result
