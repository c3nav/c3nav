from django.http import Http404
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from c3nav.editor.hosters import hosters
from c3nav.editor.serializers import HosterSerializer


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
