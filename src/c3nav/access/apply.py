from django.db.models import Q

from c3nav.mapdata.inclusion import get_maybe_invisible_areas_names


def can_access(request, item):
    # todo implement this
    return True


def filter_queryset_by_access(request, queryset, filter_location_inclusion=False):
    # todo implement this
    return queryset if request.c3nav_full_access else queryset.filter(public=True)


def filter_arealocations_by_access(request, queryset):
    # todo implement this
    if request.c3nav_full_access:
        return queryset
    return queryset.filter(Q(Q(public=True), ~Q(routing_inclusion='needs_permission')) |
                           Q(name__in=request.c3nav_access_list))


def get_visible_areas(request):
    areas = [':full' if request.c3nav_full_access else ':base']
    areas += [name for name in get_maybe_invisible_areas_names() if name in request.c3nav_access_list]
    return areas
