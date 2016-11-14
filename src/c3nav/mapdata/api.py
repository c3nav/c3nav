import mimetypes
import os
from collections import OrderedDict

from django.conf import settings
from django.core.files import File
from django.http import Http404, HttpResponse
from rest_framework.decorators import detail_route
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet, ViewSet

from c3nav.mapdata.models import MAPITEM_TYPES, Level, Package, Source
from c3nav.mapdata.models.geometry import Area, Building, Door, Obstacle
from c3nav.mapdata.permissions import PackageAccessMixin, filter_source_queryset
from c3nav.mapdata.serializers.features import (AreaSerializer, BuildingSerializer, DoorSerializer,
                                                MapItemTypeSerializer, ObstacleSerializer)
from c3nav.mapdata.serializers.main import LevelSerializer, PackageSerializer, SourceSerializer


class MapItemTypeViewSet(ViewSet):
    """
    List and retrieve feature types
    """
    lookup_field = 'name'

    def list(self, request):
        serializer = MapItemTypeSerializer(MAPITEM_TYPES.values(), many=True, context={'request': request})
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        if pk not in MAPITEM_TYPES:
            raise Http404
        serializer = MapItemTypeSerializer(MAPITEM_TYPES[pk], context={'request': request})
        return Response(serializer.data)


class MapItemViewSet(ViewSet):
    """
    List all features.
    This endpoint combines the list endpoints for all feature types.
    """

    def list(self, request):
        result = OrderedDict()
        for name, model in MAPITEM_TYPES.items():
            endpoint = model._meta.default_related_name
            result[endpoint] = eval(model.__name__+'ViewSet').as_view({'get': 'list'})(request).data
        return Response(result)


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
        return filter_source_queryset(self.request, super().get_queryset())

    @detail_route(methods=['get'])
    def image(self, request, name=None):
        source = self.get_object()
        response = HttpResponse(content_type=mimetypes.guess_type(source.name)[0])
        image_path = os.path.join(settings.MAP_ROOT, source.package.directory, 'sources', source.name)
        for chunk in File(open(image_path, 'rb')).chunks():
            response.write(chunk)
        return response


class BuildingViewSet(PackageAccessMixin, ReadOnlyModelViewSet):
    """
    List and retrieve Inside Areas
    """
    queryset = Building.objects.all()
    serializer_class = BuildingSerializer
    lookup_field = 'name'
    lookup_value_regex = '[^/]+'


class AreaViewSet(PackageAccessMixin, ReadOnlyModelViewSet):
    """
    List and retrieve Areas
    """
    queryset = Area.objects.all()
    serializer_class = AreaSerializer
    lookup_field = 'name'
    lookup_value_regex = '[^/]+'


class ObstacleViewSet(PackageAccessMixin, ReadOnlyModelViewSet):
    """
    List and retrieve Obstcales
    """
    queryset = Obstacle.objects.all()
    serializer_class = ObstacleSerializer
    lookup_field = 'name'
    lookup_value_regex = '[^/]+'


class DoorViewSet(PackageAccessMixin, ReadOnlyModelViewSet):
    """
    List and retrieve Doors
    """
    queryset = Door.objects.all()
    serializer_class = DoorSerializer
    lookup_field = 'name'
    lookup_value_regex = '[^/]+'
