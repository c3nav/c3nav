from django.conf import settings
from django.utils.translation import ugettext_lazy as _
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission
from shapely.geometry import box

from c3nav.mapdata.models import Source
from c3nav.mapdata.utils.cache import get_packages_cached
from c3nav.mapdata.utils.misc import get_dimensions


def get_public_packages():
    packages_cached = get_packages_cached()
    return [packages_cached[name] for name in settings.PUBLIC_PACKAGES]


def get_unlocked_packages_names(request, packages_cached=None):
    if packages_cached is None:
        packages_cached = get_packages_cached()
    if settings.DIRECT_EDITING:
        return packages_cached.keys()
    return set(settings.PUBLIC_PACKAGES) | set(request.session.get('unlocked_packages', ()))


def get_unlocked_packages(request, packages_cached=None):
    if packages_cached is None:
        packages_cached = get_packages_cached()
    names = get_unlocked_packages_names(request, packages_cached=packages_cached)
    return tuple(packages_cached[name] for name in names if name in packages_cached)


def can_access_package(request, package):
    return settings.DEBUG or package.name in get_unlocked_packages_names(request)


def filter_queryset_by_package_access(request, queryset):
    return queryset if settings.DIRECT_EDITING else queryset.filter(package__in=get_unlocked_packages(request))


def get_public_private_area(level):
    width, height = get_dimensions()
    everything = box(0, 0, width, height)
    public_area = level.public_geometries.areas_and_doors
    private_area = everything.difference(public_area)
    return public_area, private_area


class LockedMapFeatures(BasePermission):
    def has_object_permission(self, request, view, obj):
        if isinstance(obj, Source):
            if not can_access_package(request, obj.package):
                raise PermissionDenied(_('This Source belongs to a package you don\'t have access to.'))
        return True
