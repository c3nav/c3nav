import mimetypes
import os
from collections import OrderedDict

from django.conf import settings
from django.core.files import File
from django.http import HttpResponse
from rest_framework.decorators import detail_route
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet, ViewSet

from c3nav.mapdata.models import GEOMETRY_MAPITEM_TYPES, Level, Package, Source
from c3nav.mapdata.permissions import filter_queryset_by_package_access
from c3nav.mapdata.serializers.main import LevelSerializer, PackageSerializer, SourceSerializer


class GeometryTypeViewSet(ViewSet):
    """
    Lists all geometry types.
    """

    def list(self, request):
        return Response([
            OrderedDict((
                ('name', name),
                ('title', str(mapitemtype._meta.verbose_name)),
                ('title_plural', str(mapitemtype._meta.verbose_name_plural)),
            )) for name, mapitemtype in GEOMETRY_MAPITEM_TYPES.items()
        ])


class GeometryViewSet(ViewSet):
    """
    List all geometries.
    You can filter by adding one or more level, package, type or name GET parameters.
    """

    def list(self, request):
        types = request.GET.getlist('type')
        valid_types = list(GEOMETRY_MAPITEM_TYPES.keys())
        if not types:
            types = valid_types
        else:
            types = [t for t in types if t in valid_types]

        levels = request.GET.getlist('level')
        packages = request.GET.getlist('package')
        names = request.GET.getlist('name')

        if levels:
            levels = tuple(Level.objects.filter(name__in=levels))
        if packages:
            packages = tuple(Package.objects.filter(name__in=packages))

        results = []
        for t in types:
            mapitemtype = GEOMETRY_MAPITEM_TYPES[t]
            queryset = mapitemtype.objects.all()
            if packages:
                queryset = queryset.filter(package__in=packages)
            if levels:
                if hasattr(mapitemtype, 'level'):
                    queryset = queryset.filter(level__in=levels)
                elif hasattr(mapitemtype, 'levels'):
                    queryset = queryset.filter(levels__in=levels)
                else:
                    queryset = queryset.none()
            if names:
                queryset = queryset.filter(name__in=names)
            queryset = filter_queryset_by_package_access(request, queryset)
            queryset = queryset.order_by('name')

            for field_name in ('package', 'level', 'crop_to_level', 'elevator'):
                if hasattr(mapitemtype, field_name):
                    queryset = queryset.select_related(field_name)

            for field_name in ('levels', ):
                if hasattr(mapitemtype, field_name):
                    queryset.prefetch_related(field_name)

            results.extend(sum((obj.to_geojson() for obj in queryset), []))

        return Response(results)


class PackageViewSet(ReadOnlyModelViewSet):
    """
    Retrieve packages the map consists of.
    """
    queryset = Package.objects.all()
    serializer_class = PackageSerializer
    lookup_field = 'name'
    lookup_value_regex = '[^/]+'
    filter_fields = ('name', 'depends')
    ordering_fields = ('name',)
    ordering = ('name',)
    search_fields = ('name',)


class LevelViewSet(ReadOnlyModelViewSet):
    """
    List and retrieve levels.
    """
    queryset = Level.objects.all()
    serializer_class = LevelSerializer
    lookup_field = 'name'
    lookup_value_regex = '[^/]+'
    filter_fields = ('altitude', 'package')
    ordering_fields = ('altitude', 'package')
    ordering = ('altitude',)
    search_fields = ('name',)


class SourceViewSet(ReadOnlyModelViewSet):
    """
    List and retrieve source images (to use as a drafts).
    """
    queryset = Source.objects.all()
    serializer_class = SourceSerializer
    lookup_field = 'name'
    lookup_value_regex = '[^/]+'
    filter_fields = ('package',)
    ordering_fields = ('name', 'package')
    ordering = ('name',)
    search_fields = ('name',)

    def get_queryset(self):
        return filter_queryset_by_package_access(self.request, super().get_queryset())

    @detail_route(methods=['get'])
    def image(self, request, name=None):
        source = self.get_object()
        response = HttpResponse(content_type=mimetypes.guess_type(source.name)[0])
        image_path = os.path.join(settings.MAP_ROOT, source.package.directory, 'sources', source.name)
        for chunk in File(open(image_path, 'rb')).chunks():
            response.write(chunk)
        return response
