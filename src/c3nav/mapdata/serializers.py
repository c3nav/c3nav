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
    name = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()
    title_plural = serializers.SerializerMethodField()
    geomtype = serializers.CharField()
    color = serializers.CharField()

    def get_name(self, obj):
        return obj.__name__.lower()

    def get_title(self, obj):
        return str(obj._meta.verbose_name)

    def get_title_plural(self, obj):
        return str(obj._meta.verbose_name_plural)


class FeatureSerializer(serializers.Serializer):
    name = serializers.CharField()
    feature_type = serializers.SerializerMethodField()
    level = serializers.SerializerMethodField()
    package = serializers.SerializerMethodField()
    geometry = GeometryField()

    def get_feature_type(self, obj):
        return obj.__class__.__name__.lower()

    def get_level(self, obj):
        return obj.level.name

    def get_package(self, obj):
        return obj.package.name

