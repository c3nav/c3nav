from collections import OrderedDict

from django.conf import settings
from django.utils.translation import ugettext_lazy as _

from c3nav.access.apply import can_access_package
from c3nav.mapdata.models import AreaLocation, LocationGroup


def get_default_include_avoid():
    include = set()
    avoid = set()

    locations = list(AreaLocation.objects.exclude(routing_inclusion='default'))
    locations += list(LocationGroup.objects.exclude(routing_inclusion='default'))

    for location in locations:
        if location.routing_inclusion != 'allow_avoid':
            avoid.add(location.location_id)

    return include, avoid


# Todo: add cache
def get_includables_avoidables(request):
    includables = []
    avoidables = []

    locations = list(AreaLocation.objects.exclude(routing_inclusion='default'))
    locations += list(LocationGroup.objects.exclude(routing_inclusion='default'))

    if settings.DEBUG:
        includables.append((':nonpublic', _('non-public areas')))
        avoidables.append((':public', _('public areas')))

    for location in locations:
        item = (location.location_id, location.title)

        # Todo: allow by access token
        if not can_access_package(request, location.package):
            continue

        # Todo: allow by access token
        if location.routing_inclusion == 'needs_permission' and not settings.DEBUG:
            continue

        if location.routing_inclusion == 'allow_avoid':
            avoidables.append(item)
        else:
            includables.append(item)

    return OrderedDict(includables), OrderedDict(avoidables)


def parse_include_avoid(request, include_input, avoid_input):
    includable, avoidable = get_includables_avoidables(request)
    include_input = set(include_input) & set(includable)
    avoid_input = set(avoid_input) & set(avoidable)

    default_include, default_avoid = get_default_include_avoid()

    include = set(default_include) | include_input
    avoid = set(default_avoid) - include_input | avoid_input

    return ':nonpublic' in includable, include, avoid
