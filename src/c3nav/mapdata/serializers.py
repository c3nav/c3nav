from django.utils.translation import ugettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from shapely.geometry import mapping, shape

from c3nav.editor.hosters import get_hoster_for_package
from c3nav.mapdata.models import Feature, Level, Package, Source
from c3nav.mapdata.utils import format_geojson


class GeometryField(serializers.DictField):
    """
    shapely geometry objects serialized using GeoJSON
    """
    default_error_messages = {
        'invalid': _('Invalid GeoJSON.')
    }

    def to_representation(self, obj):
        geojson = format_geojson(mapping(obj), round=False)
        return super().to_representation(geojson)

    def to_internal_value(self, data):
        geojson = super().to_internal_value(data)
        try:
            return shape(geojson)
        except:
            raise ValidationError(_('Invalid GeoJSON.'))


class PackageSerializer(serializers.ModelSerializer):
    hoster = serializers.SerializerMethodField()
    depends = serializers.SlugRelatedField(slug_field='name', many=True, read_only=True)

    class Meta:
        model = Package
        fields = ('name', 'home_repo', 'commit_id', 'depends', 'bounds', 'public', 'hoster')

    def get_depends(self, obj):
        return self.recursive_value(PackageSerializer, obj.depends, many=True)

    def get_hoster(self, obj):
        return get_hoster_for_package(obj).name


class LevelSerializer(serializers.ModelSerializer):
    package = serializers.SlugRelatedField(slug_field='name', read_only=True)

    class Meta:
        model = Level
        fields = ('name', 'altitude', 'package')


class SourceSerializer(serializers.ModelSerializer):
    package = serializers.SlugRelatedField(slug_field='name', read_only=True)

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
