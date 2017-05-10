from collections import OrderedDict

from django.utils.translation import ugettext_lazy as _


def get_default_include_avoid():
    include = set()
    avoid = set()

    locations = list(AreaLocation.objects.exclude(routing_inclusion='default'))

    for location in locations:
        if location.routing_inclusion != 'allow_avoid':
            avoid.add(location.location_id)

    return include, avoid


# Todo: add cache
def get_includables_avoidables(request):
    includables = []
    avoidables = []

    locations = list(AreaLocation.objects.exclude(routing_inclusion='default'))

    if request.c3nav_full_access:
        includables.append((':nonpublic', _('non-public areas')))
        avoidables.append((':public', _('public areas')))

    for location in locations:
        item = (location.location_id, location.title)

        if location.location_id not in request.c3nav_access_list and not request.c3nav_full_access:
            if location.routing_inclusion == 'needs_permission':
                continue

        if location.routing_inclusion == 'allow_avoid':
            avoidables.append(item)
        else:
            includables.append(item)

    return OrderedDict(includables), OrderedDict(avoidables)


def get_maybe_invisible_areas():
    return AreaLocation.objects.exclude(routing_inclusion='default')


def get_maybe_invisible_areas_names():
    return tuple(area.name for area in get_maybe_invisible_areas())


def parse_include_avoid(request, include_input, avoid_input):
    includable, avoidable = get_includables_avoidables(request)
    include_input = set(include_input) & set(includable)
    avoid_input = set(avoid_input) & set(avoidable)

    default_include, default_avoid = get_default_include_avoid()

    include = set(default_include) | include_input
    avoid = set(default_avoid) - include_input | avoid_input

    return ':nonpublic' in includable, include, avoid
