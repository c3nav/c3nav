from django.utils.translation import ugettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.reverse import reverse
from shapely.geometry import mapping, shape

from c3nav.api.serializers import RecursiveSerializerMixin
from c3nav.editor.hosters import get_hoster_for_package
from c3nav.mapdata.models import Feature, Level, Package, Source
from c3nav.mapdata.models.feature import FEATURE_TYPES
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


class PackageSerializer(RecursiveSerializerMixin, serializers.ModelSerializer):
    hoster = serializers.SerializerMethodField()
    depends = serializers.SerializerMethodField()

    class Meta:
        model = Package
        fields = ('name', 'url', 'home_repo', 'commit_id', 'depends', 'bounds', 'public', 'hoster')
        sparse_exclude = ('depends', 'hoster')
        extra_kwargs = {
            'url': {'view_name': 'api:package-detail', 'lookup_field': 'name'}
        }

    def get_depends(self, obj):
        return self.recursive_value(PackageSerializer, obj.depends, many=True)

    def get_hoster(self, obj):
        from c3nav.editor.serializers import HosterSerializer
        return self.recursive_value(HosterSerializer, get_hoster_for_package(obj))


class LevelSerializer(RecursiveSerializerMixin, serializers.ModelSerializer):
    package = PackageSerializer(context={'sparse': True})

    class Meta:
        model = Level
        fields = ('name', 'url', 'altitude', 'package')
        sparse_exclude = ('package',)
        extra_kwargs = {
            'url': {'view_name': 'api:level-detail', 'lookup_field': 'name'}
        }


class SourceSerializer(RecursiveSerializerMixin, serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    package = PackageSerializer(context={'sparse': True})

    class Meta:
        model = Source
        fields = ('name', 'url', 'image_url', 'package', 'bounds')
        sparse_exclude = ('package', )
        extra_kwargs = {
            'url': {'view_name': 'api:source-detail', 'lookup_field': 'name'}
        }

    def get_image_url(self, obj):
        return reverse('api:source-image', args=(obj.name, ), request=self.context.get('request'))


class FeatureTypeSerializer(serializers.Serializer):
    name = serializers.CharField()
    url = serializers.HyperlinkedIdentityField(view_name='api:featuretype-detail')
    title = serializers.CharField()
    title_plural = serializers.CharField()
    geomtype = serializers.CharField()
    color = serializers.CharField()


class FeatureSerializer(RecursiveSerializerMixin, serializers.ModelSerializer):
    titles = serializers.JSONField()
    feature_type = serializers.SerializerMethodField()
    level = LevelSerializer()
    package = PackageSerializer()
    geometry = GeometryField()

    class Meta:
        model = Feature
        fields = ('name', 'url', 'title', 'feature_type', 'level', 'titles', 'package', 'geometry')
        sparse_exclude = ('feature_type', 'level', 'package')
        extra_kwargs = {
            'lookup_field': 'name',
            'url': {'view_name': 'api:feature-detail', 'lookup_field': 'name'}
        }

    def get_feature_type(self, obj):
        return self.recursive_value(FeatureTypeSerializer, FEATURE_TYPES.get(obj.feature_type))
