from rest_framework.serializers import ModelSerializer

from ..mapdata.models import Level, Package, Source


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


class SourceSerializer(BoundsMixin, ModelSerializer):
    class Meta:
        model = Source
        fields = ('name', 'package')
