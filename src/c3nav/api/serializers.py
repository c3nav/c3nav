from django.conf import settings

from rest_framework.serializers import ModelSerializer

from ..mapdata.models import Level, Package, Source
from .permissions import can_access_package


class BoundsMixin:
    def to_representation(self, obj):
        result = super().to_representation(obj)
        if obj.bottom is not None:
            result['bounds'] = ((obj.bottom, obj.left), (obj.top, obj.right))
        return result


class LevelSerializer(ModelSerializer):
    class Meta:
        model = Level
        fields = ('name', 'altitude', 'package')


class PackageSerializer(BoundsMixin, ModelSerializer):
    class Meta:
        model = Package
        fields = ('name', 'depends')

    def to_representation(self, obj):
        result = super().to_representation(obj)
        result['public'] = obj.name in settings.PUBLIC_PACKAGES
        if 'request' in self.context:
            result['access'] = can_access_package(self.context['request'], obj)
        return result


class SourceSerializer(BoundsMixin, ModelSerializer):
    class Meta:
        model = Source
        fields = ('name', 'package')
