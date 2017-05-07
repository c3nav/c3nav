import re

from django.db.models import Q

from c3nav.access.apply import filter_arealocations_by_access, filter_queryset_by_access
from c3nav.mapdata.models import AreaLocation, LocationGroup
from c3nav.mapdata.models.locations import PointLocation
from c3nav.mapdata.utils.cache import get_sections_cached


def get_location(request, location_id):
    match = re.match('^c:(?P<section>[0-9]+):(?P<x>[0-9]+):(?P<y>[0-9]+)$', location_id)
    if match:
        levels = get_sections_cached()
        section = levels.get(int(match.group('section')))
        if section is None:
            return None
        return PointLocation(section=section, x=int(match.group('x')) / 100, y=int(match.group('y')) / 100, request=request)

    if location_id.startswith('g:'):
        queryset = LocationGroup.objects.filter(Q(slug=location_id[2:], can_search=True))
        return filter_queryset_by_access(request, queryset).first()

    return filter_arealocations_by_access(request, AreaLocation.objects.filter(slug=location_id, can_search=True)).first()


def filter_words(queryset, words):
    for word in words:
        queryset = queryset.filter(Q(name__icontains=word) | Q(titles__icontains=word))
    return queryset


def search_location(request, search):
    results = []
    location = get_location(request, search)
    if location:
        results.append(location)

    words = search.split(' ')[:10]

    queryset = LocationGroup.objects.filter(can_seach=True).order_by('name')
    if isinstance(location, LocationGroup):
        queryset.exclude(name='g:' + location.name)
    results += list(filter_words(filter_queryset_by_access(request, queryset), words)[:10])

    queryset = AreaLocation.objects.filter(can_seach=True).order_by('name')
    if isinstance(location, AreaLocation):
        queryset.exclude(name=location.name)
    results += sorted(filter_words(filter_arealocations_by_access(request, queryset), words),
                      key=AreaLocation.get_sort_key, reverse=True)

    return results
