from django.http import Http404
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ViewSet

from ...editor.hosters import hosters
from ...mapdata.models import Feature
from ..serializers import FeatureSerializer, HosterSerializer


class HosterViewSet(ViewSet):
    """
    Get Package Hosters
    """
    def list(self, request, version=None):
        serializer = HosterSerializer(hosters.values(), many=True, context={'request': request})
        return Response(serializer.data)

    def retrieve(self, request, pk=None, version=None):
        if pk not in hosters:
            raise Http404
        serializer = HosterSerializer(hosters[pk], context={'request': request})
        return Response(serializer.data)


class FeatureViewSet(ModelViewSet):
    """
    Get all Map Features including ones that are only part of the current session
    """
    queryset = Feature.objects.all()
    serializer_class = FeatureSerializer
    lookup_value_regex = '[^/]+'
