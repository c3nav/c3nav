import mimetypes
import os

from django.conf import settings
from django.core.files import File
from django.http import HttpResponse
from rest_framework.decorators import detail_route
from rest_framework.viewsets import ReadOnlyModelViewSet

from ...mapdata.models import Level, Package, Source
from ..permissions import filter_source_queryset
from ..serializers import LevelSerializer, PackageSerializer, SourceSerializer
from .cache import AccessCachedViewSetMixin, CachedViewSetMixin


class LevelViewSet(CachedViewSetMixin, ReadOnlyModelViewSet):
    """
    Returns a list of all levels on the map.
    """
    queryset = Level.objects.all()
    serializer_class = LevelSerializer
    lookup_value_regex = '[^/]+'
    filter_fields = ('altitude', 'package')
    ordering_fields = ('altitude', 'package')
    ordering = ('altitude',)
    search_fields = ('name',)


class PackageViewSet(AccessCachedViewSetMixin, ReadOnlyModelViewSet):
    """
    Returns a list of all packages the map consists of.
    """
    queryset = Package.objects.all()
    serializer_class = PackageSerializer
    lookup_value_regex = '[^/]+'
    filter_fields = ('name', 'depends')
    ordering_fields = ('name',)
    ordering = ('name',)
    search_fields = ('name',)


class SourceViewSet(AccessCachedViewSetMixin, ReadOnlyModelViewSet):
    """
    Returns a list of source images (to use as a drafts).
    Call /sources/{name}/image to get the image.
    """
    queryset = Source.objects.all()
    serializer_class = SourceSerializer
    lookup_value_regex = '[^/]+'
    filter_fields = ('package',)
    ordering_fields = ('name', 'package')
    ordering = ('name',)
    search_fields = ('name',)

    def get_queryset(self):
        return filter_source_queryset(self.request, super().get_queryset())

    @detail_route(methods=['get'])
    def image(self, request, pk=None, version=None):
        source = self.get_object()
        response = HttpResponse(content_type=mimetypes.guess_type(source.name)[0])
        image_path = os.path.join(settings.MAP_ROOT, source.package.directory, 'sources', source.name)
        for chunk in File(open(image_path, 'rb')).chunks():
            response.write(chunk)
        return response
