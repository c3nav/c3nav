from rest_framework import serializers

from c3nav.mapdata.models.features import Inside, Room
from c3nav.mapdata.serializers.fields import GeometryField


class FeatureTypeSerializer(serializers.Serializer):
    name = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()
    title_plural = serializers.SerializerMethodField()
    endpoint = serializers.SerializerMethodField()
    geomtype = serializers.CharField()
    color = serializers.CharField()

    def get_name(self, obj):
        return obj.__name__.lower()

    def get_title(self, obj):
        return str(obj._meta.verbose_name)

    def get_title_plural(self, obj):
        return str(obj._meta.verbose_name_plural)

    def get_endpoint(self, obj):
        return obj._meta.default_related_name


class InsideSerializer(serializers.ModelSerializer):
    level = serializers.SlugRelatedField(slug_field='name', read_only=True)
    package = serializers.SlugRelatedField(slug_field='name', read_only=True)
    geometry = GeometryField()

    class Meta:
        model = Inside
        fields = ('name', 'level', 'package', 'geometry')


class RoomSerializer(serializers.ModelSerializer):
    level = serializers.SlugRelatedField(slug_field='name', read_only=True)
    package = serializers.SlugRelatedField(slug_field='name', read_only=True)
    geometry = GeometryField()

    class Meta:
        model = Room
        fields = ('name', 'level', 'package', 'geometry')
