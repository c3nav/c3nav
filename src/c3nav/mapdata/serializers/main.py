from rest_framework import serializers

from c3nav.mapdata.models.section import Section
from c3nav.mapdata.models.source import Source


class SectionSerializer(serializers.ModelSerializer):
    titles = serializers.DictField()

    class Meta:
        model = Section
        fields = ('id', 'name', 'altitude', 'slug', 'public', 'titles', 'can_search', 'can_search', 'color')


class LocationSerializer(serializers.ModelSerializer):
    titles = serializers.DictField()

    class Meta:
        model = Section
        fields = ('id', 'name', 'slug', 'public', 'titles', 'can_search', 'can_search', 'color')


class SourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Source
        fields = ('id', 'name', 'bounds')
