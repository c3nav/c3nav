from rest_framework import serializers

from c3nav.editor.hosters import get_hoster_for_package
from c3nav.mapdata.models import Level, Package, Source


class PackageSerializer(serializers.ModelSerializer):
    hoster = serializers.SerializerMethodField()
    depends = serializers.SlugRelatedField(slug_field='name', many=True, read_only=True)

    class Meta:
        model = Package
        fields = ('name', 'home_repo', 'commit_id', 'depends', 'bounds', 'public', 'hoster')

    def get_depends(self, obj):
        return self.recursive_value(PackageSerializer, obj.depends, many=True)

    def get_hoster(self, obj):
        hoster = get_hoster_for_package(obj)
        return hoster.name if hoster else None


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
