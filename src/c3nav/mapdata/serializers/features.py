from rest_framework import serializers

from c3nav.mapdata.models.features import Area, Building, Door, Obstacle
from c3nav.mapdata.serializers.fields import GeometryField


class FeatureTypeSerializer(serializers.Serializer):
    name = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()
    title_plural = serializers.SerializerMethodField()
    endpoint = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
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

    def get_description(self, obj):
        return str(obj.__doc__.strip())


class FeatureSerializer(serializers.ModelSerializer):
    level = serializers.SlugRelatedField(slug_field='name', read_only=True)
    package = serializers.SlugRelatedField(slug_field='name', read_only=True)
    geometry = GeometryField()


class BuildingSerializer(FeatureSerializer):
    class Meta:
        model = Building
        fields = ('name', 'level', 'package', 'geometry')


class AreaSerializer(FeatureSerializer):
    class Meta:
        model = Area
        fields = ('name', 'level', 'package', 'geometry')


class ObstacleSerializer(FeatureSerializer):
    class Meta:
        model = Obstacle
        fields = ('name', 'level', 'package', 'geometry', 'height')


class DoorSerializer(FeatureSerializer):
    class Meta:
        model = Door
        fields = ('name', 'level', 'package', 'geometry')
