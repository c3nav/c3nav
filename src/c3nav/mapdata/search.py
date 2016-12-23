import re

from django.db.models import Q

from c3nav.access.apply import filter_queryset_by_access
from c3nav.mapdata.models import AreaLocation, LocationGroup
from c3nav.mapdata.models.locations import PointLocation
from c3nav.mapdata.utils.cache import get_levels_cached


def get_location(request, name):
    match = re.match('^c:(?P<level>[a-z0-9-_]+):(?P<x>[0-9]+):(?P<y>[0-9]+)$', name)
    if match:
        levels = get_levels_cached()
        level = levels.get(match.group('level'))
        if level is None:
            return None
        return PointLocation(level=level, x=int(match.group('x'))/100, y=int(match.group('y'))/100)

    if name.startswith('g:'):
        return filter_queryset_by_access(request, LocationGroup.objects.filter(name=name[2:], can_search=True)).first()

    return filter_queryset_by_access(request, AreaLocation.objects.filter(name=name, can_search=True)).first()


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

    queryset = AreaLocation.objects.filter(can_seach=True)
    if isinstance(location, AreaLocation):
        queryset.exclude(name=location.name)
    results += sorted(filter_words(filter_queryset_by_access(request, queryset), words),
                      key=AreaLocation.get_sort_key, reverse=True)

    queryset = LocationGroup.objects.filter(can_seach=True)
    if isinstance(location, LocationGroup):
        queryset.exclude(name='g:'+location.name)
    results += list(filter_words(filter_queryset_by_access(request, queryset), words)[:10])

    return results
