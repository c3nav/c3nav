from django.db.models import Q

from c3nav.access.apply import filter_arealocations_by_access, filter_queryset_by_access
from c3nav.mapdata.models import LocationGroup


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
