import mimetypes
import os

from django.conf import settings
from django.core.files import File
from django.http import Http404, HttpResponse

from rest_framework.decorators import detail_route
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet, ViewSet

from .cache import AccessCachedViewSetMixin, CachedViewSetMixin
from .models import FEATURE_TYPES, Feature, Level, Package, Source
from .permissions import filter_source_queryset
from .serializers import FeatureSerializer, FeatureTypeSerializer, LevelSerializer, PackageSerializer, SourceSerializer


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


class FeatureTypeViewSet(ViewSet):
    """
    Get Feature types
    """

    def list(self, request, version=None):
        serializer = FeatureTypeSerializer(FEATURE_TYPES.values(), many=True, context={'request': request})
        return Response(serializer.data)

    def retrieve(self, request, pk=None, version=None):
        if pk not in FEATURE_TYPES:
            raise Http404
        serializer = FeatureTypeSerializer(FEATURE_TYPES[pk], context={'request': request})
        return Response(serializer.data)


class FeatureViewSet(ReadOnlyModelViewSet):
    """
    Get all Map Features including ones that are only part of the current session
    """
    queryset = Feature.objects.all().prefetch_related('featuretitles')
    serializer_class = FeatureSerializer
    lookup_value_regex = '[^/]+'
