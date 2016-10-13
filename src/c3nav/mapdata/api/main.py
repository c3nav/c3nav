import mimetypes
import os

from django.conf import settings
from django.core.files import File
from django.http import HttpResponse
from rest_framework.decorators import detail_route
from rest_framework.viewsets import ReadOnlyModelViewSet

from c3nav.mapdata.models import Level, Package, Source
from c3nav.mapdata.permissions import filter_source_queryset
from c3nav.mapdata.serializers.main import LevelSerializer, PackageSerializer, SourceSerializer


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
        return filter_source_queryset(self.request, super().get_queryset())

    @detail_route(methods=['get'])
    def image(self, request, pk=None):
        source = self.get_object()
        response = HttpResponse(content_type=mimetypes.guess_type(source.name)[0])
        image_path = os.path.join(settings.MAP_ROOT, source.package.directory, 'sources', source.name)
        for chunk in File(open(image_path, 'rb')).chunks():
            response.write(chunk)
        return response
