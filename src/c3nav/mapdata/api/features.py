from collections import OrderedDict

from django.http import Http404
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet, ViewSet

from c3nav.mapdata.models import FEATURE_TYPES
from c3nav.mapdata.models.features import Area, Building, Door, Obstacle
from c3nav.mapdata.serializers.features import (AreaSerializer, BuildingSerializer, DoorSerializer,
                                                FeatureTypeSerializer, ObstacleSerializer)


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


class FeatureViewSet(ViewSet):
    """
    List all features.
    This endpoint combines the list endpoints for all feature types.
    """

    def list(self, request):
        result = OrderedDict()
        for name, model in FEATURE_TYPES.items():
            endpoint = model._meta.default_related_name
            result[endpoint] = eval(model.__name__+'ViewSet').as_view({'get': 'list'})(request).data
        return Response(result)


class BuildingViewSet(ReadOnlyModelViewSet):
    """
    List and retrieve Inside Areas
    """
    queryset = Building.objects.all()
    serializer_class = BuildingSerializer
    lookup_field = 'name'
    lookup_value_regex = '[^/]+'


class AreaViewSet(ReadOnlyModelViewSet):
    """
    List and retrieve Areas
    """
    queryset = Area.objects.all()
    serializer_class = AreaSerializer
    lookup_field = 'name'
    lookup_value_regex = '[^/]+'


class ObstacleViewSet(ReadOnlyModelViewSet):
    """
    List and retrieve Obstcales
    """
    queryset = Obstacle.objects.all()
    serializer_class = ObstacleSerializer
    lookup_field = 'name'
    lookup_value_regex = '[^/]+'


class DoorViewSet(ReadOnlyModelViewSet):
    """
    List and retrieve Doors
    """
    queryset = Door.objects.all()
    serializer_class = DoorSerializer
    lookup_field = 'name'
    lookup_value_regex = '[^/]+'
