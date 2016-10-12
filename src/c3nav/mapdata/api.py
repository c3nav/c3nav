import mimetypes
import os
from itertools import chain

from django.conf import settings
from django.core.files import File
from django.http import Http404, HttpResponse
from rest_framework.decorators import detail_route
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet, ViewSet

from c3nav.mapdata.models import FEATURE_TYPES, Level, Package, Source
from c3nav.mapdata.models.features import Feature
from c3nav.mapdata.permissions import filter_source_queryset
from c3nav.mapdata.serializers import (FeatureSerializer, FeatureTypeSerializer, LevelSerializer, PackageSerializer,
                                       SourceSerializer)


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


class FeatureTypeViewSet(ViewSet):
    """
    List and retrieve feature types
    """
    lookup_field = 'name'

    def list(self, request):
        serializer = FeatureTypeSerializer(FEATURE_TYPES.values(), many=True, context={'request': request})
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        if pk not in FEATURE_TYPES:
            raise Http404
        serializer = FeatureTypeSerializer(FEATURE_TYPES[pk], context={'request': request})
        return Response(serializer.data)


class FeatureViewSet(ReadOnlyModelViewSet):
    """
    List and retrieve map features you have access to
    """
    model = Feature
    base_name = 'feature'
    serializer_class = FeatureSerializer
    lookup_field = 'name'
    lookup_value_regex = '[^/]+'

    def get_queryset(self):
        querysets = []
        for name, model in FEATURE_TYPES.items():
            querysets.append(model.objects.all())
        return chain(*querysets)

