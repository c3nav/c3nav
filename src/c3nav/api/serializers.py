from django.conf import settings

from rest_framework import serializers

from ..editor.hosters import get_hoster_for_package
from ..mapdata.models import Level, Package, Source
from .permissions import can_access_package


class LevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Level
        fields = ('name', 'altitude', 'package')


class PackageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Package
        fields = ('name', 'home_repo', 'commit_id', 'depends', 'bounds')

    def to_representation(self, obj):
        result = super().to_representation(obj)
        result['public'] = obj.name in settings.PUBLIC_PACKAGES
        hoster = get_hoster_for_package(obj)
        if 'request' in self.context:
            result['access_granted'] = can_access_package(self.context['request'], obj)
        if hoster is not None:
            result['hoster'] = hoster.name
        return result


class SourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Source
        fields = ('name', 'package', 'bounds')


class HosterSerializer(serializers.Serializer):
    name = serializers.CharField()
    base_url = serializers.CharField()

    def to_representation(self, obj):
        result = super().to_representation(obj)
        result['packages'] = tuple(obj.get_packages().values_list('name', flat=True))
        if 'request' in self.context:
            result['signed_in'] = obj.is_access_granted(self.context['request'])
        return result
