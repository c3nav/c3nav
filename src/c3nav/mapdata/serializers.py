from django.utils.translation import ugettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from shapely.geometry import mapping, shape

from .models import Feature, Level, Package, Source
from .utils import sort_geojson


class GeometryField(serializers.DictField):
    """
    shapely geometry objects serialized using GeoJSON
    """
    default_error_messages = {
        'invalid': _('Invalid GeoJSON.')
    }

    def to_representation(self, obj):
        geojson = sort_geojson(mapping(obj))
        return super().to_representation(geojson)

    def to_internal_value(self, data):
        geojson = super().to_internal_value(data)
        try:
            return shape(geojson)
        except:
            raise ValidationError(_('Invalid GeoJSON.'))


class LevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Level
        fields = ('name', 'altitude', 'package')


class PackageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Package
        fields = ('name', 'home_repo', 'commit_id', 'depends', 'bounds', 'public')
        readonly_fields = ('commit_id',)


class SourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Source
        fields = ('name', 'package', 'bounds')


class FeatureTypeSerializer(serializers.Serializer):
    name = serializers.CharField()
    title = serializers.CharField()
    title_plural = serializers.CharField()
    geomtype = serializers.CharField()
    color = serializers.CharField()


class FeatureSerializer(serializers.ModelSerializer):
    titles = serializers.JSONField()
    geometry = GeometryField()

    class Meta:
        model = Feature
        fields = ('name', 'title', 'feature_type', 'level', 'titles', 'package', 'geometry')
