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
from c3nav.mapdata.models.locations import LocationTag


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
        measurement_lookup[pos.rounded_pk] = (measurement.pk, grid_square, space_slug, level_label)
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
    # todo: modernize this, this is just the pre location hierarchy code adapted to work again
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
    level_indices = {}
    space_slugs = {}
    area_slugs = {}
    poi_slugs = {}

    for level_id, level_index in Level.objects.values_list("pk", "level_index"):
        result['locations']['by_level'][level_index] = 0
        result['coordinates']['by_level'][level_index] = 0
        level_indices[level_id] = level_index

    for space in Space.objects.prefetch_related("locations").only("id"):
        location = space.get_location()
        space_slugs[space.id] = location.effective_slug
        result['locations']['by_space'][location.effective_slug] = 0
        result['coordinates']['by_space'][location.effective_slug] = 0

    for area in Area.objects.prefetch_related("locations").only("id"):
        location = area.get_location()
        area_slugs[area.id] = location.effective_slug
        if getattr(location, 'can_search', False) or getattr(location, 'can_describe', False):
            result['coordinates']['by_area'][location.effective_slug] = 0

    for poi in POI.objects.prefetch_related("locations").only("id"):
        location = poi.get_location()
        poi_slugs[poi.id] = location.effective_slug
        if getattr(location, 'can_search', False) or getattr(location, 'can_describe', False):
            result['coordinates']['by_poi'][location.effective_slug] = 0

    for tag in LocationTag.objects.filter(children__isnull=False).only("id"):
        # todo: by group??
        result['locations']['by_group'][tag.effective_slug] = 0

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
            result['coordinates']['by_level'][level_indices[location.nearby.level]] += value
            if location.nearby.space is None:
                continue
            result['coordinates']['by_space'][space_slugs[location.nearby.space]] += value
            for area in location.nearby.areas:
                result['coordinates']['by_area'][area_slugs[area]] += value
            if location.nearby.near_area:
                result['coordinates']['by_area'][area_slugs[location.nearby.near_area]] += value
            if location.nearby.near_poi:
                result['coordinates']['by_poi'][poi_slugs[location.nearby.near_poi]] += value
        else:
            result['locations']['total'] += value
            location = getattr(location, 'target', location)
            if hasattr(location, 'space_id'):
                result['locations']['by_space'][space_slugs[location.space_id]] += value
            if hasattr(location, 'level_id'):
                result['locations']['by_level'][level_indices[location.level_id]] += value
            # todo: improve this
            if hasattr(location, "display_superlocations"):
                for display in location.display_superlocations:
                    result['locations']['by_group'][display["slug"]] += value

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
