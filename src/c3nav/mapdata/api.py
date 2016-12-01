import mimetypes
import os

from django.conf import settings
from django.core.files import File
from django.http import HttpResponse
from rest_framework.decorators import detail_route
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet, ViewSet

from c3nav.mapdata.models import GEOMETRY_MAPITEM_TYPES, Level, Package, Source
from c3nav.mapdata.permissions import filter_queryset_by_package_access
from c3nav.mapdata.serializers.main import LevelSerializer, PackageSerializer, SourceSerializer


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

        results = []
        for t in types:
            mapitemtype = GEOMETRY_MAPITEM_TYPES[t]
            queryset = mapitemtype.objects.all()
            if packages:
                queryset = queryset.filter(package__name__in=packages)
            if levels:
                if hasattr(mapitemtype, 'level'):
                    queryset = queryset.filter(level__name__in=levels)
                elif hasattr(mapitemtype, 'levels'):
                    queryset = queryset.filter(levels__name__in=levels)
                else:
                    queryset = queryset.none()
            if names:
                queryset = queryset.filter(name__in=names)
            queryset = filter_queryset_by_package_access(request, queryset)
            queryset.prefetch_related('package', 'level').order_by('name')
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
