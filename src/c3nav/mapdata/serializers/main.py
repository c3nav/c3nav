from rest_framework import serializers

from c3nav.mapdata.models.section import Section
from c3nav.mapdata.models.source import Source


class SectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Section
        fields = ('id', 'name', 'altitude')


class SourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Source
        fields = ('id', 'name', 'bounds')
