from django.conf import settings
from django.utils.translation import ugettext_lazy as _
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from c3nav.mapdata.models import Package, Source


def get_unlocked_packages_names(request):
    return set(settings.PUBLIC_PACKAGES) | set(request.session.get('unlocked_packages', ()))


def get_unlocked_packages(request):
    names = get_unlocked_packages_names(request)
    return tuple(Package.objects.filter(name__in=names))


def can_access_package(request, package):
    return settings.DEBUG or package.name in get_unlocked_packages_names(request)


def filter_queryset_by_package_access(request, queryset):
    return queryset if settings.DIRECT_EDITING else queryset.filter(package__in=get_unlocked_packages(request))


class LockedMapFeatures(BasePermission):
    def has_object_permission(self, request, view, obj):
        if isinstance(obj, Source):
            if not can_access_package(request, obj.package):
                raise PermissionDenied(_('This Source belongs to a package you don\'t have access to.'))
        return True
